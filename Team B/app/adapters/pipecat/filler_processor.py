import asyncio
import wave
import os
import random
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame, TranscriptionFrame, LLMFullResponseStartFrame,
    OutputAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, TextFrame
)

# Short, natural, human-like acknowledgements spoken via TTS when the WAV fillers
# are unavailable or disabled.  These are contextually randomised so they never
# feel repetitive across a single call.
_TEXT_FILLERS = [
    "Mm-hmm.",
    "Let me check.",
    "One moment.",
    "Sure, just a second.",
    "Alright.",
    "Got it, one sec.",
]


class LatencyFillerProcessor(FrameProcessor):
    """
    Monitors transcription frames and plays a short filler audio (or speaks a
    short acknowledgement via TTS) if the LLM response is delayed by more than
    a given threshold.

    Priority:
      1. Pre-recorded WAV files (played as raw audio chunks, no TTS latency).
      2. Short text fillers sent as TTSSpeakFrame (goes through TTS pipeline).
    """

    def __init__(
        self,
        filler_wav_paths: list[str] = None,
        delay_threshold_ms: int = 400,
        event_bus=None,
        session_id=None,
        shared_state=None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if filler_wav_paths is None:
            filler_wav_paths = ["hmm.wav", "wait_a_minute.wav", "let_me_think.wav"]

        self.delay_threshold = delay_threshold_ms / 1000.0
        self._wait_task = None
        self._audio_frames_list = []
        self.event_bus = event_bus
        self.session_id = session_id
        self.shared_state = shared_state if shared_state is not None else {}

        # Track which text fillers have been used so we don't repeat
        self._used_text_fillers: list[str] = []

        if self.event_bus and self.session_id:
            asyncio.create_task(self._subscribe_to_events())

        # Preload all audio files
        try:
            import soundfile as sf
        except ImportError:
            sf = None

        for path in filler_wav_paths:
            try:
                if os.path.exists(path):
                    frames = []
                    if sf is not None:
                        data, sample_rate = sf.read(path, dtype="int16")
                        num_channels = 1 if data.ndim == 1 else data.shape[1]
                        bytes_data = data.tobytes()
                    else:
                        with wave.open(path, "rb") as wf:
                            sample_rate = wf.getframerate()
                            num_channels = wf.getnchannels()
                            bytes_data = wf.readframes(wf.getnframes())

                    # Chunk into 50 ms pieces
                    bytes_per_sample = 2
                    chunk_bytes = int(sample_rate * 0.05) * bytes_per_sample * num_channels

                    for i in range(0, len(bytes_data), chunk_bytes):
                        chunk = bytes_data[i : i + chunk_bytes]
                        frames.append(
                            OutputAudioRawFrame(
                                audio=chunk,
                                sample_rate=sample_rate,
                                num_channels=num_channels,
                            )
                        )
                    self._audio_frames_list.append(frames)
                    logger.info(
                        f"Loaded {len(frames)} chunks from {path} for filler processor."
                    )
                else:
                    logger.warning(f"Filler audio {path} not found — will use text filler as fallback.")
            except Exception as e:
                logger.error(f"Failed to load filler audio {path}: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_text_filler(self) -> str:
        """Return a text filler that hasn't been used recently, cycling when all are exhausted."""
        available = [f for f in _TEXT_FILLERS if f not in self._used_text_fillers]
        if not available:
            # All used — reset and start over
            self._used_text_fillers = []
            available = list(_TEXT_FILLERS)
        chosen = random.choice(available)
        self._used_text_fillers.append(chosen)
        return chosen

    async def _play_filler_if_delayed(self):
        """Task: wait for threshold, then play filler audio or speak a text filler."""
        try:
            await asyncio.sleep(self.delay_threshold)

            if self.shared_state.get("hangup_requested"):
                logger.debug("Hangup requested — skipping filler playback.")
                return

            if self._audio_frames_list:
                # --- Preferred: play pre-recorded WAV ---
                logger.info(
                    f"LLM response delayed >{self.delay_threshold}s. Playing WAV filler audio."
                )
                audio_frames = random.choice(self._audio_frames_list)

                await self.push_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
                for frame in audio_frames:
                    await self.push_frame(frame, FrameDirection.DOWNSTREAM)
                    await asyncio.sleep(0.01)  # yield to event loop

                # Tag stop frame as filler so CallTerminationProcessor ignores it
                stop_frame = TTSStoppedFrame()
                stop_frame.is_filler = True
                await self.push_frame(stop_frame, FrameDirection.DOWNSTREAM)

            else:
                # --- Fallback: send a short text phrase through TTS pipeline ---
                phrase = self._pick_text_filler()
                logger.info(
                    f"LLM response delayed >{self.delay_threshold}s. Speaking text filler: '{phrase}'"
                )
                try:
                    from pipecat.frames.frames import TTSSpeakFrame
                    await self.push_frame(
                        TTSSpeakFrame(text=phrase), FrameDirection.DOWNSTREAM
                    )
                except Exception as e:
                    logger.warning(f"Could not push TTSSpeakFrame for text filler: {e}")

        except asyncio.CancelledError:
            logger.debug("Filler wait task cancelled — LLM responded in time.")

    async def _subscribe_to_events(self):
        async def cancel_wait(event):
            if event.session_id == self.session_id:
                if self._wait_task and not self._wait_task.done():
                    self._wait_task.cancel()
                    logger.debug("Filler wait task cancelled by EventBus event.")
                self._wait_task = None

        await self.event_bus.subscribe("ThinkingStarted", cancel_wait)
        await self.event_bus.subscribe("ResponseGenerated", cancel_wait)
        await self.event_bus.subscribe("SpeakingStarted", cancel_wait)

    # ------------------------------------------------------------------
    # Frame processing
    # ------------------------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        from pipecat.frames.frames import LLMContextFrame

        # Trigger filler wait when user message is about to reach the LLM
        if isinstance(frame, LLMContextFrame):
            messages = (
                frame.context.messages
                if hasattr(frame.context, "messages")
                else frame.context.get_messages()
            )
            is_user_msg = any(m.get("role") == "user" for m in messages)
            if is_user_msg:
                if self.shared_state.get("hangup_requested"):
                    logger.debug("Hangup requested — not starting filler wait.")
                    return
                if self._wait_task and not self._wait_task.done():
                    self._wait_task.cancel()
                self._wait_task = asyncio.create_task(self._play_filler_if_delayed())

        # Cancel the filler as soon as the LLM or TTS starts responding
        elif isinstance(frame, (LLMFullResponseStartFrame, TextFrame, TTSStartedFrame)):
            if self._wait_task and not self._wait_task.done():
                self._wait_task.cancel()
            self._wait_task = None

        await self.push_frame(frame, direction)
