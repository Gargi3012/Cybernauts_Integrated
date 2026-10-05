"""
Dynamic LLM-Generated Conversational Filler & Acknowledgement Processor

Architecture:
  - Sits downstream of the LLM and TurnGuardFilter, upstream of ToolInterceptor and SarvamTTSService.
  - The LLM dynamically decides whether an acknowledgement/filler is appropriate based on
    conversation context, language (English, Hindi, Hinglish), and tone.
  - When the user asks to pause/wait ("wait a minute", "ek minute ruko", etc.), the LLM emits
    a natural acknowledgement with should_wait=True, prompting the AI to acknowledge and wait.
  - When the response is ready quickly and no acknowledgement is needed, the LLM emits a direct
    response (or acknowledgement: null) with ZERO delay.
  - The filler text is synthesized using the EXACT SAME Sarvam TTS pipeline as normal speech.
  - No additional LLM round-trip is created.
  - Interruption/barge-in and stale response suppression are managed via TurnGuard and Pipecat frames.
"""

import re
import json
import asyncio
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    InterruptionFrame,
)


class DynamicLLMFillerProcessor(FrameProcessor):
    """
    Parses LLM output for dynamic filler/acknowledgements and streams them
    to Sarvam TTS ahead of the main response when needed.

    Restores true incremental streaming for conversational text:
    - Normal conversational text frames are forwarded downstream IMMEDIATELY.
    - No waiting for complete JSON, end-of-response, or sentence boundaries.
    - TurnGuard compatibility: validates turn_id on every frame to discard stale chunks.
    - Dynamic acknowledgements via tags (<ack> or <ack wait='true'>) or legacy JSON remain supported.
    """

    def __init__(self, session_id: str = None, shared_state: dict = None, event_bus=None, **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id or "unknown"
        self.shared_state = shared_state if shared_state is not None else {}
        self.event_bus = event_bus

        # Stream state for current turn
        self._buffer = ""
        self._mode = "detecting"  # "detecting", "streaming", "tag", "json", "waiting"
        self._ack_emitted = False
        self._filler_active = False
        self._current_turn_id = 0

    def _get_turn_id(self) -> int:
        return self.shared_state.get("current_turn_id", 0)

    def _get_correlation(self) -> str:
        turn_id = self._get_turn_id()
        lead_id = self.shared_state.get("lead_id", "N/A")
        dispatch_id = self.shared_state.get("dispatch_id", "N/A")
        call_uuid = self.shared_state.get("call_uuid", "N/A")
        return f"session_id={self.session_id} | turn_id={turn_id} | dispatch_id={dispatch_id} | lead_id={lead_id} | call_uuid={call_uuid}"

    async def _emit_filler_text(self, ack_text: str, should_wait: bool, direction: FrameDirection):
        """Send dynamic acknowledgement text to Sarvam TTS pipeline."""
        if not ack_text or not ack_text.strip():
            return

        if self.shared_state.get("ending_call") or self.shared_state.get("termination_requested") or self.shared_state.get("hangup_requested"):
            logger.info(f"[FILLER] Suppressing filler text during call termination: '{ack_text}'")
            return

        turn_id = self._get_turn_id()
        self._ack_emitted = True
        self._filler_active = True

        logger.warning(
            f"[FILLER] FILLER_GENERATED | {self._get_correlation()} | "
            f"text='{ack_text}' | should_wait={should_wait}"
        )

        # Notify EventBus if available
        if self.event_bus:
            try:
                from app.events.event_types import Event
                await self.event_bus.publish(
                    "FillerGenerated",
                    Event(
                        session_id=self.session_id,
                        payload={
                            "text": ack_text,
                            "should_wait": should_wait,
                            "turn_id": turn_id
                        }
                    )
                )
            except Exception as e:
                logger.debug(f"[FILLER] EventBus publish ignored: {e}")

        # Push TextFrame to Sarvam TTS tagged as filler
        filler_frame = TextFrame(text=ack_text)
        filler_frame.is_filler = True
        filler_frame._turn_id = turn_id

        logger.info(f"[FILLER] FILLER_TTS_STARTED | {self._get_correlation()}")
        await self.push_frame(filler_frame, direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # 1. New user turn context — log request
        if isinstance(frame, LLMContextFrame):
            turn_id = self._get_turn_id()
            logger.info(f"[FILLER] FILLER_GENERATION_REQUESTED | {self._get_correlation()}")
            await self.push_frame(frame, direction)
            return

        # 2. LLM response start
        elif isinstance(frame, LLMFullResponseStartFrame):
            current_turn_id = self._get_turn_id()
            frame_turn_id = getattr(frame, "_turn_id", current_turn_id)
            self._current_turn_id = frame_turn_id if frame_turn_id is not None else current_turn_id
            self._buffer = ""
            self._mode = "detecting"
            self._ack_emitted = False
            self._filler_active = False

            if frame_turn_id is not None and frame_turn_id < current_turn_id:
                logger.warning(f"[FILLER] STALE StartFrame turn_id={frame_turn_id} < {current_turn_id}")
                return

            await self.push_frame(frame, direction)
            return

        # 3. User barge-in / Interruption while filler or response is active
        elif isinstance(frame, (UserStartedSpeakingFrame, InterruptionFrame)):
            if self._filler_active:
                logger.warning(f"[FILLER] FILLER_INTERRUPTED | {self._get_correlation()}")
                self._filler_active = False
            self._buffer = ""
            self._mode = "detecting"
            self._ack_emitted = False
            await self.push_frame(frame, direction)
            return

        # 4. TTS completion
        elif isinstance(frame, TTSStoppedFrame):
            if getattr(frame, "is_filler", False):
                logger.info(f"[FILLER] FILLER_TTS_COMPLETED | {self._get_correlation()}")
                self._filler_active = False
            await self.push_frame(frame, direction)
            return

        # 5. Streaming TextFrame from LLM
        elif isinstance(frame, TextFrame):
            current_turn_id = self._get_turn_id()
            frame_turn_id = getattr(frame, "_turn_id", self._current_turn_id)

            # TurnGuard validation: discard stale chunks
            if frame_turn_id is not None and frame_turn_id < current_turn_id:
                logger.warning(
                    f"[FILLER] STALE_CHUNK_DISCARDED | frame_turn={frame_turn_id} < current_turn={current_turn_id}"
                )
                return

            # Check call termination / pause suppression
            if self.shared_state.get("ending_call"):
                ending_turn_id = self.shared_state.get("ending_call_turn_id")
                current_turn_id = self.shared_state.get("current_turn_id", 0)
                if ending_turn_id is not None and current_turn_id > ending_turn_id:
                    logger.info(
                        f"[FILLER] ENDING_CALL active: suppressing TextFrame for subsequent turn {current_turn_id}"
                    )
                    return

            if self._mode == "waiting" or self.shared_state.get("user_pause"):
                return

            text = frame.text
            if not text:
                return

            # Fast path: already in streaming mode -> forward immediately!
            if self._mode == "streaming":
                if not hasattr(frame, "_turn_id"):
                    frame._turn_id = self._current_turn_id
                await self.push_frame(frame, direction)
                return

            self._buffer += text

            # Mode: Detecting (initial tokens of the turn)
            if self._mode == "detecting":
                stripped = self._buffer.lstrip()
                if not stripped:
                    return

                # Check for tag start
                if stripped.startswith("<"):
                    if stripped.startswith("<ack"):
                        self._mode = "tag"
                        # Fall through to tag handling below
                    elif len(stripped) < 4:
                        # Ambiguous: could be <ack
                        return
                    else:
                        # Not an <ack> tag, enter streaming immediately
                        self._mode = "streaming"
                        to_send = self._buffer
                        self._buffer = ""
                        out_frame = TextFrame(text=to_send)
                        out_frame._turn_id = self._current_turn_id
                        await self.push_frame(out_frame, direction)
                        return

                # Check for JSON start
                elif stripped.startswith("{"):
                    # Check if complete JSON is already available
                    if stripped.endswith("}"):
                        try:
                            data = json.loads(stripped)
                            ack = data.get("acknowledgement")
                            resp = data.get("response", "")
                            should_wait = bool(data.get("should_wait", False))
                            call_end = bool(data.get("call_end", False))

                            if ack and not self._ack_emitted:
                                await self._emit_filler_text(ack.strip(), should_wait, direction)

                            if should_wait:
                                self.shared_state["user_pause"] = True
                                logger.info(f"[FILLER] USER_PAUSE confirmed | {self._get_correlation()}")
                                self._mode = "waiting"
                                self._buffer = ""
                                return
                            elif resp and resp.strip():
                                out_frame = TextFrame(text=resp.strip())
                                out_frame._turn_id = self._current_turn_id
                                await self.push_frame(out_frame, direction)

                            if call_end:
                                self.shared_state["hangup_requested"] = True

                            self._buffer = ""
                            self._mode = "streaming"
                            return
                        except Exception:
                            pass

                    # Ambiguous / partial JSON: check if it's filler schema or ordinary text
                    if "acknowledgement" in self._buffer or "response" in self._buffer or len(stripped) < 25:
                        self._mode = "json"
                        # Fall through to json handling below
                    else:
                        # Ordinary text containing '{': do not buffer!
                        self._mode = "streaming"
                        to_send = self._buffer
                        self._buffer = ""
                        out_frame = TextFrame(text=to_send)
                        out_frame._turn_id = self._current_turn_id
                        await self.push_frame(out_frame, direction)
                        return

                else:
                    # PLAIN CONVERSATIONAL TEXT — STREAM IMMEDIATELY!
                    self._mode = "streaming"
                    to_send = self._buffer
                    self._buffer = ""
                    out_frame = TextFrame(text=to_send)
                    out_frame._turn_id = self._current_turn_id
                    await self.push_frame(out_frame, direction)
                    return

            # Mode: Tag mode (<ack>...</ack>)
            if self._mode == "tag":
                tag_match = re.search(r'<ack(?:\s+wait=[\"\']?(true|false)[\"\']?)?>(.*?)</ack>', self._buffer, re.DOTALL | re.I)
                if tag_match:
                    wait_val = (tag_match.group(1) or "").lower() == "true"
                    ack_text = tag_match.group(2).strip()

                    if not self._ack_emitted:
                        await self._emit_filler_text(ack_text, wait_val, direction)

                    # Remove tag from buffer
                    self._buffer = self._buffer[tag_match.end():]

                    if wait_val:
                        self.shared_state["user_pause"] = True
                        logger.info(f"[FILLER] USER_PAUSE active | {self._get_correlation()} — suppressing subsequent text")
                        self._buffer = ""
                        self._mode = "waiting"
                        return
                    else:
                        # Enter streaming mode immediately for remaining response
                        self._mode = "streaming"
                        if self._buffer:
                            out_frame = TextFrame(text=self._buffer)
                            out_frame._turn_id = self._current_turn_id
                            await self.push_frame(out_frame, direction)
                            self._buffer = ""
                        return
                elif len(self._buffer) > 100:
                    # Tag malformed safety fallback: flush and stream
                    self._mode = "streaming"
                    out_frame = TextFrame(text=self._buffer)
                    out_frame._turn_id = self._current_turn_id
                    await self.push_frame(out_frame, direction)
                    self._buffer = ""
                    return
                return

            # Mode: JSON mode (legacy / backward-compatibility)
            if self._mode == "json":
                # Check for acknowledgement
                if not self._ack_emitted:
                    ack_m = re.search(r'\"acknowledgement\"\s*:\s*(?:\"((?:\\\\.|[^\"])*)\"|null)', self._buffer)
                    if ack_m:
                        ack_val = ack_m.group(1)
                        wait_m = re.search(r'\"should_wait\"\s*:\s*(true|false)', self._buffer, re.I)
                        should_wait = (wait_m.group(1).lower() == "true") if wait_m else False

                        if ack_val and ack_val.strip() and ack_val.lower() != "null":
                            await self._emit_filler_text(ack_val.strip(), should_wait, direction)
                        else:
                            self._ack_emitted = True
                            logger.debug(f"[FILLER] LLM decided no acknowledgement needed | {self._get_correlation()}")

                # Check should_wait
                if "true" in re.findall(r'\"should_wait\"\s*:\s*(true)', self._buffer, re.I):
                    self.shared_state["user_pause"] = True

                # Check call_end
                if "true" in re.findall(r'\"call_end\"\s*:\s*(true)', self._buffer, re.I):
                    self.shared_state["hangup_requested"] = True

                # If JSON has closed, parse and forward response immediately
                stripped_buf = self._buffer.strip()
                if stripped_buf.endswith("}"):
                    try:
                        data = json.loads(stripped_buf)
                        resp = data.get("response", "")
                        should_wait = bool(data.get("should_wait", False))
                        if not should_wait and resp and resp.strip():
                            out_frame = TextFrame(text=resp.strip())
                            out_frame._turn_id = self._current_turn_id
                            await self.push_frame(out_frame, direction)
                        self._buffer = ""
                        self._mode = "streaming"
                        return
                    except Exception:
                        pass

                # Safety: If buffer grows beyond 150 chars without matching JSON schema, release to streaming
                if len(self._buffer) > 150 and not any(k in self._buffer for k in ["acknowledgement", "response"]):
                    self._mode = "streaming"
                    out_frame = TextFrame(text=self._buffer)
                    out_frame._turn_id = self._current_turn_id
                    await self.push_frame(out_frame, direction)
                    self._buffer = ""
                return

        # 6. LLM response end
        elif isinstance(frame, LLMFullResponseEndFrame):
            turn_id = getattr(frame, "_turn_id", self._current_turn_id)
            current_turn_id = self._get_turn_id()
            if turn_id is not None and turn_id < current_turn_id:
                logger.warning(f"[FILLER] STALE_RESPONSE_END_DISCARDED | turn_id={turn_id}")
                self._buffer = ""
                self._mode = "detecting"
                await self.push_frame(frame, direction)
                return

            if self._mode == "json" and self._buffer.strip():
                # Final JSON parse of the complete response
                try:
                    data = json.loads(self._buffer.strip())
                    ack = data.get("acknowledgement")
                    resp = data.get("response", "")
                    should_wait = bool(data.get("should_wait", False))
                    call_end = bool(data.get("call_end", False))

                    if ack and not self._ack_emitted:
                        await self._emit_filler_text(ack.strip(), should_wait, direction)

                    if should_wait:
                        self.shared_state["user_pause"] = True
                        logger.info(f"[FILLER] USER_PAUSE confirmed | {self._get_correlation()}")
                    elif resp and resp.strip():
                        out_frame = TextFrame(text=resp.strip())
                        out_frame._turn_id = self._current_turn_id
                        await self.push_frame(out_frame, direction)

                    if call_end:
                        self.shared_state["hangup_requested"] = True
                except Exception:
                    # Fallback regex extraction if JSON was truncated
                    resp_m = re.search(r'\"response\"\s*:\s*\"((?:\\\\.|[^\"])*)', self._buffer)
                    wait_m = re.search(r'\"should_wait\"\s*:\s*(true|false)', self._buffer, re.I)
                    should_wait = (wait_m.group(1).lower() == "true") if wait_m else False

                    if not should_wait and resp_m:
                        clean_resp = resp_m.group(1).replace('\\"', '"').replace('\\n', ' ')
                        if clean_resp.strip():
                            out_frame = TextFrame(text=clean_resp.strip())
                            out_frame._turn_id = self._current_turn_id
                            await self.push_frame(out_frame, direction)

            elif self._mode == "tag" and self._buffer.strip():
                clean_tail = re.sub(r'<ack.*?>.*?</ack>', '', self._buffer, flags=re.DOTALL).strip()
                if clean_tail and not self.shared_state.get("user_pause"):
                    out_frame = TextFrame(text=clean_tail)
                    out_frame._turn_id = self._current_turn_id
                    await self.push_frame(out_frame, direction)

            elif self._buffer.strip() and not self.shared_state.get("user_pause") and self._mode != "waiting":
                out_frame = TextFrame(text=self._buffer)
                out_frame._turn_id = self._current_turn_id
                await self.push_frame(out_frame, direction)

            self._buffer = ""
            self._mode = "detecting"
            await self.push_frame(frame, direction)
            return

        else:
            await self.push_frame(frame, direction)

