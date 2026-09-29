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
    """

    def __init__(self, session_id: str = None, shared_state: dict = None, event_bus=None, **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id or "unknown"
        self.shared_state = shared_state if shared_state is not None else {}
        self.event_bus = event_bus

        # Stream state for current turn
        self._buffer = ""
        self._mode = "detecting"  # "detecting", "json", "tag", "passthrough"
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
                # Generic dictionary payload event
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
            self._buffer = ""
            self._mode = "detecting"
            self._ack_emitted = False
            self._filler_active = False
            self._current_turn_id = getattr(frame, "_turn_id", self._get_turn_id())
            await self.push_frame(frame, direction)
            return

        # 3. User barge-in / Interruption while filler is playing
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
            text = frame.text
            self._buffer += text

            # Mode: detecting format
            if self._mode == "detecting":
                stripped = self._buffer.strip()
                if not stripped:
                    return

                if stripped.startswith("{"):
                    self._mode = "json"
                elif stripped.startswith("<ack"):
                    self._mode = "tag"
                elif len(stripped) >= 6:
                    # Neither JSON nor tag — fast response, enter passthrough immediately
                    self._mode = "passthrough"
                    if self._buffer:
                        await self.push_frame(TextFrame(text=self._buffer), direction)
                        self._buffer = ""
                    return
                else:
                    # Need a few more chars to disambiguate
                    return

            # Mode: Passthrough (fast response without filler)
            if self._mode == "passthrough":
                if self._buffer:
                    await self.push_frame(TextFrame(text=self._buffer), direction)
                    self._buffer = ""
                return

            # Mode: Tag <ack wait="true">...</ack>
            if self._mode == "tag":
                tag_match = re.search(r'<ack(?:\s+wait=[\"\']?(true|false)[\"\']?)?>(.*?)</ack>', self._buffer, re.DOTALL | re.I)
                if tag_match:
                    wait_val = (tag_match.group(1) or "").lower() == "true"
                    ack_text = tag_match.group(2).strip()
                    
                    if not self._ack_emitted:
                        await self._emit_filler_text(ack_text, wait_val, direction)

                    # Remove the tag from buffer
                    self._buffer = self._buffer[tag_match.end():]
                    
                    if wait_val:
                        # User pause requested: hold and wait for user, suppress further text
                        self.shared_state["user_pause"] = True
                        logger.info(f"[FILLER] USER_PAUSE active | {self._get_correlation()} — suppressing subsequent text")
                        self._buffer = ""
                        self._mode = "waiting"
                        return
                    else:
                        # Switch to passthrough for the main response
                        self._mode = "passthrough"
                        if self._buffer.strip():
                            await self.push_frame(TextFrame(text=self._buffer), direction)
                            self._buffer = ""
                return

            # Mode: JSON {"acknowledgement": "...", "response": "...", "should_wait": bool}
            if self._mode == "json":
                # Check if acknowledgement string is closed
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

                # Check if should_wait is true in JSON
                if "true" in re.findall(r'\"should_wait\"\s*:\s*(true)', self._buffer, re.I):
                    self.shared_state["user_pause"] = True

                # Check if call_end is true in JSON
                if "true" in re.findall(r'\"call_end\"\s*:\s*(true)', self._buffer, re.I):
                    self.shared_state["hangup_requested"] = True

                return

        # 6. LLM response end
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._mode == "json":
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
                        await self.push_frame(TextFrame(text=resp.strip()), direction)

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
                            await self.push_frame(TextFrame(text=clean_resp.strip()), direction)
            
            elif self._mode == "tag":
                # Flush any leftover response after tag
                clean_tail = re.sub(r'<ack.*?>.*?</ack>', '', self._buffer, flags=re.DOTALL).strip()
                if clean_tail and not self.shared_state.get("user_pause"):
                    await self.push_frame(TextFrame(text=clean_tail), direction)

            elif self._mode in ("detecting", "passthrough"):
                if self._buffer.strip():
                    await self.push_frame(TextFrame(text=self._buffer), direction)

            self._buffer = ""
            self._mode = "detecting"
            await self.push_frame(frame, direction)
            return

        else:
            await self.push_frame(frame, direction)
