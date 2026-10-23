"""
Pillar 2 — Plivo Telephony WebSocket Transport Factory
Builds a FastAPI WebSocket transport utilizing AtomicPlivoFrameSerializer and
AtomicFastAPIWebsocketTransport.
Handles 8kHz mu-law audio conversion, bidirectional streaming, atomic response
generation validation, write serialization, resampler state flushing, and
graceful auto-hangup.
"""

import asyncio
import base64
import io
import json
import time
import wave
from typing import Any, Optional
from fastapi import WebSocket
from loguru import logger

from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    Frame,
    StartFrame,
    EndFrame,
    CancelFrame,
    InterruptionFrame,
    AudioRawFrame,
    OutputAudioRawFrame,
    InputAudioRawFrame,
    InputDTMFFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    OutputTransportReadyFrame,
)
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
    FastAPIWebsocketOutputTransport,
    FastAPIWebsocketCallbacks,
    FastAPIWebsocketClient,
)
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.processors.frame_processor import FrameDirection

PLIVO_SAMPLE_RATE = 8000


class AtomicPlivoFrameSerializer(PlivoFrameSerializer):
    """
    Enhanced PlivoFrameSerializer providing:
    1. Response-generation ID validation before serializing outbound audio,
       dropping any late chunks that arrive from superseded or cancelled turns.
    2. Atomic resampler flushing on InterruptionFrame, resetting filter state
       to prevent discontinuity clicks on subsequent responses.
    3. Non-blocking acknowledgment tracking for Plivo 'clearedAudio' events.
    4. Strict PCM16 sample alignment (2-byte multiple) so odd-byte slices
       never cause codec distortion.
    """

    def __init__(
        self,
        stream_id: str,
        call_id: Optional[str] = None,
        auth_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        params: Optional[PlivoFrameSerializer.InputParams] = None,
        shared_state: Optional[dict] = None,
    ):
        super().__init__(
            stream_id=stream_id,
            call_id=call_id,
            auth_id=auth_id,
            auth_token=auth_token,
            params=params,
        )
        self._shared_state: Optional[dict] = shared_state
        self._outbound_seq: int = 0
        self._carry_pcm_bytes: bytes = b""
        self._current_gen_id: Optional[int] = None

    def set_shared_state(self, shared_state: dict):
        self._shared_state = shared_state

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """Serializes a Pipecat frame to Plivo WebSocket format with generation gating."""
        if (
            self._params.auto_hang_up
            and not self._hangup_attempted
            and isinstance(frame, (EndFrame, CancelFrame))
        ):
            self._carry_pcm_bytes = b""
            self._current_gen_id = None
            self._hangup_attempted = True
            await self._hang_up_call()
            return None

        elif isinstance(frame, InterruptionFrame):
            # Atomic Interruption: Invalidate active generation immediately
            int_gen = getattr(frame, "_generation_id", None)
            now = time.monotonic()
            if self._shared_state is not None:
                cur_active = self._shared_state.get("active_generation_id")
                # If this interruption is for an older generation that was already superseded, ignore
                if int_gen is not None and cur_active is not None and int_gen < cur_active:
                    logger.info(
                        f"[PLIVO_INTERRUPTION] LATE_INTERRUPTION_IGNORED | "
                        f"int_gen={int_gen} | active_gen={cur_active}"
                    )
                    return None

                cur_gen = self._shared_state.get("current_generation_id", 0)
                self._shared_state["active_generation_id"] = None
                self._shared_state["interrupted_generation_id"] = cur_gen
                self._shared_state["tts_speaking"] = False
                self._shared_state["plivo_clear_audio_sent"] = True
                self._shared_state["plivo_clear_audio_time"] = now

            # Reset output resampler and carry byte so filter state never bleeds into next response
            self._output_resampler = create_stream_resampler()
            self._carry_pcm_bytes = b""
            self._current_gen_id = None

            logger.info(
                f"[INTERRUPTION_DIAGNOSTICS] PLIVO_CLEAR_AUDIO_SENT | "
                f"stream_id={self._stream_id} | timestamp={now:.3f}"
            )
            answer = {"event": "clearAudio", "streamId": self._stream_id}
            return json.dumps(answer)

        elif isinstance(frame, AudioRawFrame):
            # Validate response-generation ID when shared_state is configured
            raw_gen = getattr(frame, "_generation_id", getattr(frame, "generation_id", None))
            valid_gen = isinstance(raw_gen, int) and raw_gen > 0
            frame_gen_id = raw_gen if valid_gen else None

            if self._shared_state is not None:
                active_gen_id = self._shared_state.get("active_generation_id")
                interrupted_gen_id = self._shared_state.get("interrupted_generation_id")
                is_control = getattr(frame, "_is_control_audio", False) or self._shared_state.get("allow_untagged_audio", False)

                # Case 1: Untagged or malformed generation ID audio is rejected unless explicit control audio
                if frame_gen_id is None:
                    if not is_control:
                        self._shared_state["late_chunks_dropped"] = self._shared_state.get("late_chunks_dropped", 0) + 1
                        logger.warning(
                            f"[SERIALIZER] UNTAGGED_OR_MALFORMED_AUDIO_DROPPED | "
                            f"raw_gen={raw_gen} | active_gen={active_gen_id} | bytes={len(frame.audio)}"
                        )
                        return None
                    # Authorized control audio allowed through

                # Case 2: Response generation has been invalidated mid-interruption / cancelled
                elif active_gen_id is None:
                    self._shared_state["late_chunks_dropped"] = self._shared_state.get("late_chunks_dropped", 0) + 1
                    logger.info(
                        f"[INTERRUPTION_DIAGNOSTICS] LATE_CHUNK_DROPPED | "
                        f"frame_gen={frame_gen_id} | active_gen=None (cancelled) | bytes={len(frame.audio)}"
                    )
                    return None

                # Case 3: Chunk stamped with an older/mismatched generation ID
                elif frame_gen_id != active_gen_id:
                    self._shared_state["late_chunks_dropped"] = self._shared_state.get("late_chunks_dropped", 0) + 1
                    logger.info(
                        f"[INTERRUPTION_DIAGNOSTICS] LATE_CHUNK_DROPPED | "
                        f"frame_gen={frame_gen_id} | active_gen={active_gen_id} | bytes={len(frame.audio)}"
                    )
                    return None

            # Track generation ID transition to avoid bleeding carry bytes across turns
            if frame_gen_id != self._current_gen_id:
                self._carry_pcm_bytes = b""
                self._current_gen_id = frame_gen_id

            data = frame.audio
            if not data and not self._carry_pcm_bytes:
                return None

            # Enforce 16-bit PCM sample alignment (must be a multiple of 2 bytes)
            # Reattach previous partial carry byte if present
            if self._carry_pcm_bytes:
                data = self._carry_pcm_bytes + data
                self._carry_pcm_bytes = b""

            if len(data) % 2 != 0:
                self._carry_pcm_bytes = data[-1:]
                data = data[:-1]
                logger.debug("[AUDIO_INTEGRITY] Odd PCM byte buffered for next chunk alignment")

            if not data:
                return None

            # Convert PCM to 8kHz μ-law for Plivo
            serialized_data = await pcm_to_ulaw(
                data, frame.sample_rate, self._plivo_sample_rate, self._output_resampler
            )
            if serialized_data is None or len(serialized_data) == 0:
                return None

            # Re-check generation validity after async resampling to catch races
            if self._shared_state is not None:
                post_active = self._shared_state.get("active_generation_id")
                if post_active is None or (frame_gen_id is not None and frame_gen_id != post_active):
                    self._shared_state["late_chunks_dropped"] = self._shared_state.get("late_chunks_dropped", 0) + 1
                    logger.info(
                        f"[INTERRUPTION_DIAGNOSTICS] CHUNK_CANCELLED_POST_RESAMPLING | "
                        f"frame_gen={frame_gen_id} | active_gen={post_active}"
                    )
                    return None

            self._outbound_seq += 1
            payload = base64.b64encode(serialized_data).decode("utf-8")
            answer = {
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate": self._plivo_sample_rate,
                    "payload": payload,
                },
                "streamId": self._stream_id,
            }
            return json.dumps(answer)

        elif isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)

        return None

    def reset_resampler(self):
        """Explicitly reset the output resampler state between turns or generations."""
        self._output_resampler = create_stream_resampler()
        self._carry_pcm_bytes = b""
        self._current_gen_id = None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Deserializes Plivo WebSocket events with non-blocking clearedAudio tracking."""
        try:
            message = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse JSON message: {data}")
            return None

        event_name = message.get("event")

        # Handle Plivo playback buffer clear acknowledgement
        if event_name == "clearedAudio":
            now = time.monotonic()
            logger.info(
                f"[PLIVO_ACK] CLEARED_AUDIO_RECEIVED | stream_id={self._stream_id} | timestamp={now:.3f}"
            )
            if self._shared_state is not None:
                self._shared_state["plivo_cleared_audio_ack"] = True
                self._shared_state["plivo_cleared_audio_ack_time"] = now
            return None

        elif event_name == "media":
            media = message.get("media", {})
            payload_base64 = media.get("payload")
            if not payload_base64:
                return None

            try:
                payload = base64.b64decode(payload_base64)
            except Exception as e:
                logger.warning(f"Failed to decode base64 media payload: {e}")
                return None

            deserialized_data = await ulaw_to_pcm(
                payload, self._plivo_sample_rate, self._sample_rate, self._input_resampler
            )
            if deserialized_data is None or len(deserialized_data) == 0:
                return None

            if len(deserialized_data) % 2 != 0:
                deserialized_data = deserialized_data[:-1]

            return InputAudioRawFrame(
                audio=deserialized_data, num_channels=1, sample_rate=self._sample_rate
            )

        elif event_name == "dtmf":
            from pipecat.frames.frames import KeypadEntry
            dtmf_data = message.get("dtmf", {})
            digit = dtmf_data.get("digit")
            if digit:
                try:
                    return InputDTMFFrame(KeypadEntry(digit))
                except ValueError:
                    logger.warning(f"Invalid DTMF digit received: {digit}")
                    return None

        return None


class AtomicMediaSender(BaseOutputTransport.MediaSender):
    """
    Subclass of BaseOutputTransport.MediaSender that:
    1. Preserves _generation_id and _is_control_audio attributes across all output chunks.
    2. Flushes the audio chunking buffer and resets the resampler on InterruptionFrame.
    3. Flushes previous audio buffer and resets resampler if generation ID changes.
    """

    def __init__(
        self,
        transport: "BaseOutputTransport",
        *,
        destination: Optional[str],
        sample_rate: int,
        audio_chunk_size: int,
        params: TransportParams,
    ):
        super().__init__(
            transport,
            destination=destination,
            sample_rate=sample_rate,
            audio_chunk_size=audio_chunk_size,
            params=params,
        )
        self._current_gen_id: Optional[int] = None
        self._is_control: bool = False

    async def handle_audio_frame(self, frame: OutputAudioRawFrame):
        if not self._params.audio_out_enabled:
            return

        frame_gen = getattr(frame, "_generation_id", getattr(frame, "generation_id", None))
        is_ctrl = getattr(frame, "_is_control_audio", False)

        # If turn/generation changed, clear any previous buffer and reset resampler
        if self._current_gen_id is not None and frame_gen is not None and frame_gen != self._current_gen_id:
            self._audio_buffer.clear()
            self._resampler = create_stream_resampler()

        self._current_gen_id = frame_gen
        self._is_control = is_ctrl

        resampled = await self._resampler.resample(
            frame.audio, frame.sample_rate, self._sample_rate
        )

        cls = type(frame)
        self._audio_buffer.extend(resampled)
        while len(self._audio_buffer) >= self._audio_chunk_size:
            chunk = cls(
                bytes(self._audio_buffer[: self._audio_chunk_size]),
                sample_rate=self._sample_rate,
                num_channels=frame.num_channels,
            )
            chunk.transport_destination = self._destination
            if self._current_gen_id is not None:
                chunk._generation_id = self._current_gen_id
            if self._is_control:
                chunk._is_control_audio = True
            await self._audio_queue.put(chunk)
            self._audio_buffer = self._audio_buffer[self._audio_chunk_size :]

    async def handle_interruptions(self, frame: InterruptionFrame):
        await super().handle_interruptions(frame)
        self._audio_buffer.clear()
        self._resampler = create_stream_resampler()
        self._current_gen_id = None
        self._is_control = False


class AtomicFastAPIWebsocketOutputTransport(FastAPIWebsocketOutputTransport):
    """
    FastAPIWebsocketOutputTransport subclass that:
    1. Uses an asyncio.Lock() to serialize all WebSocket outbound writes,
       ensuring 'clearAudio' and 'playAudio' never interleave or corrupt payloads.
    2. Uses AtomicMediaSender to preserve generation tags and avoid audio buffer leakage.
    3. Flushes the output audio send buffer on InterruptionFrame and shutdown.
    4. Blocks late audio frame writes when the active generation is invalidated.
    5. Preserves _generation_id and _is_control_audio through write_audio_frame.
    """

    def __init__(
        self,
        transport: BaseTransport,
        client: FastAPIWebsocketClient,
        params: FastAPIWebsocketParams,
        **kwargs,
    ):
        super().__init__(transport, client, params, **kwargs)
        self._write_lock = asyncio.Lock()
        self._shared_state: Optional[dict] = None

    def set_shared_state(self, shared_state: dict):
        self._shared_state = shared_state

    async def set_transport_ready(self, frame: StartFrame):
        """Called when transport is ready to stream; registers destinations using AtomicMediaSender."""
        for destination in self._params.audio_out_destinations:
            await self.register_audio_destination(destination)

        for destination in self._params.video_out_destinations:
            await self.register_video_destination(destination)

        self._media_senders[None] = AtomicMediaSender(
            self,
            destination=None,
            sample_rate=self.sample_rate,
            audio_chunk_size=self.audio_chunk_size,
            params=self._params,
        )
        await self._media_senders[None].start(frame)

        destinations = list(
            set(self._params.audio_out_destinations + self._params.video_out_destinations)
        )
        for destination in destinations:
            self._media_senders[destination] = AtomicMediaSender(
                self,
                destination=destination,
                sample_rate=self.sample_rate,
                audio_chunk_size=self.audio_chunk_size,
                params=self._params,
            )
            await self._media_senders[destination].start(frame)

        await self.push_frame(OutputTransportReadyFrame(), FrameDirection.UPSTREAM)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # Drop partially buffered audio in send buffer immediately
            self._audio_send_buffer.clear()
            self._next_send_time = 0
            for sender in self._media_senders.values():
                if hasattr(sender, "_audio_buffer"):
                    sender._audio_buffer.clear()
                if hasattr(sender, "_resampler"):
                    sender._resampler = create_stream_resampler()

    async def stop(self, frame: EndFrame):
        self._audio_send_buffer.clear()
        for sender in self._media_senders.values():
            if hasattr(sender, "_audio_buffer"):
                sender._audio_buffer.clear()
        await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        self._audio_send_buffer.clear()
        for sender in self._media_senders.values():
            if hasattr(sender, "_audio_buffer"):
                sender._audio_buffer.clear()
        await super().cancel(frame)

    async def _write_frame(self, frame: Frame):
        """Serialize outbound WebSocket frame writes with a strict lock."""
        async with self._write_lock:
            # Check generation validity if active generation was cancelled while waiting for write lock
            if isinstance(frame, AudioRawFrame):
                active_gen = self._shared_state.get("active_generation_id") if self._shared_state else None
                frame_gen = getattr(frame, "_generation_id", getattr(frame, "generation_id", None))
                is_ctrl = getattr(frame, "_is_control_audio", False)
                if not is_ctrl:
                    if active_gen is None or (frame_gen is not None and frame_gen != active_gen):
                        return
            await super()._write_frame(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        """Write an audio frame to WebSocket, ensuring generation ID and control tags are preserved."""
        if self._client.is_closing or not self._client.is_connected:
            return False

        gen_id = getattr(frame, "_generation_id", getattr(frame, "generation_id", None))
        is_ctrl = getattr(frame, "_is_control_audio", False)

        # Drop outbound audio writes if active generation has been invalidated or mismatched
        if self._shared_state is not None:
            active_gen = self._shared_state.get("active_generation_id")
            interrupted_gen = self._shared_state.get("interrupted_generation_id")
            if not is_ctrl:
                if gen_id is None:
                    return False
                if active_gen is None or gen_id != active_gen or (interrupted_gen is not None and gen_id == interrupted_gen):
                    return False

        out_sr = self.sample_rate or frame.sample_rate or getattr(self._params, "audio_out_sample_rate", None) or 8000
        out_channels = getattr(self._params, "audio_out_channels", None) or getattr(frame, "num_channels", None) or 1
        new_frame = OutputAudioRawFrame(
            audio=frame.audio,
            sample_rate=out_sr,
            num_channels=out_channels,
        )
        if gen_id is not None:
            new_frame._generation_id = gen_id
        if is_ctrl:
            new_frame._is_control_audio = True

        if self._params.add_wav_header:
            with io.BytesIO() as buffer:
                with wave.open(buffer, "wb") as wf:
                    wf.setsampwidth(2)
                    wf.setnchannels(new_frame.num_channels)
                    wf.setframerate(new_frame.sample_rate)
                    wf.writeframes(new_frame.audio)
                wav_frame = OutputAudioRawFrame(
                    buffer.getvalue(),
                    sample_rate=new_frame.sample_rate,
                    num_channels=new_frame.num_channels,
                )
                if gen_id is not None:
                    wav_frame._generation_id = gen_id
                if is_ctrl:
                    wav_frame._is_control_audio = True
                new_frame = wav_frame

        await self._write_frame(new_frame)
        await self._write_audio_sleep()
        return True


class AtomicFastAPIWebsocketTransport(FastAPIWebsocketTransport):
    """
    Subclass of FastAPIWebsocketTransport using AtomicFastAPIWebsocketOutputTransport.
    """

    def __init__(
        self,
        websocket: WebSocket,
        params: FastAPIWebsocketParams,
        input_name: Optional[str] = None,
        output_name: Optional[str] = None,
        shared_state: Optional[dict] = None,
    ):
        super().__init__(
            websocket=websocket,
            params=params,
            input_name=input_name,
            output_name=output_name,
        )
        self._shared_state = shared_state
        # Replace output transport with our atomic serialized version
        self._output = AtomicFastAPIWebsocketOutputTransport(
            self, self._client, self._params, name=self._output_name
        )
        if self._shared_state:
            self.set_shared_state(self._shared_state)

    def set_shared_state(self, shared_state: dict):
        self._shared_state = shared_state
        if hasattr(self._output, "set_shared_state"):
            self._output.set_shared_state(shared_state)
        if hasattr(self._params.serializer, "set_shared_state"):
            self._params.serializer.set_shared_state(shared_state)


def build_plivo_transport(
    websocket: WebSocket,
    stream_id: str,
    vad_analyzer: Any = None,
    call_id: Optional[str] = None,
    auth_id: Optional[str] = None,
    auth_token: Optional[str] = None,
    shared_state: Optional[dict] = None,
    **kwargs: Any,
):
    """
    Exposed factory for the main app to build the Plivo WebSocket transport via Pillar 2.

    Args:
        websocket: Active FastAPI WebSocket connection from Plivo.
        stream_id: Unique stream identifier provided by Plivo.
        vad_analyzer: Configured Silero VAD analyzer instance.
        call_id: Optional Plivo Call UUID for automatic call hangup.
        auth_id: Optional Plivo Auth ID for REST API operations.
        auth_token: Optional Plivo Auth Token for REST API operations.
        shared_state: Shared pipeline state dictionary for generation tracking.
    """
    # Accommodate callers that pass call_id as 3rd positional argument
    if vad_analyzer is not None and isinstance(vad_analyzer, str) and not hasattr(vad_analyzer, "analyze"):
        actual_call_id = vad_analyzer
        actual_auth_id = call_id
        actual_auth_token = auth_id
        actual_vad = kwargs.get("vad_analyzer", None)
    else:
        actual_call_id = call_id
        actual_auth_id = auth_id
        actual_auth_token = auth_token
        actual_vad = vad_analyzer if vad_analyzer is not None else kwargs.get("vad_analyzer", None)

    actual_shared_state = shared_state if shared_state is not None else kwargs.get("shared_state", None)

    serializer = AtomicPlivoFrameSerializer(
        stream_id=stream_id,
        call_id=actual_call_id,
        auth_id=actual_auth_id,
        auth_token=actual_auth_token,
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=PLIVO_SAMPLE_RATE,
            sample_rate=PLIVO_SAMPLE_RATE,
            auto_hang_up=bool(actual_auth_id and actual_auth_token and actual_call_id),
        ),
        shared_state=actual_shared_state,
    )

    transport = AtomicFastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=PLIVO_SAMPLE_RATE,
            audio_out_sample_rate=PLIVO_SAMPLE_RATE,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=actual_vad,
            serializer=serializer,
        ),
        shared_state=actual_shared_state,
    )

    logger.info(
        f"Plivo atomic transport constructed | stream_id={stream_id} | call_id={actual_call_id}"
    )
    return transport
