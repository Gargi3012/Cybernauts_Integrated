import re
import asyncio
import os
from loguru import logger
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import Frame, TranscriptionFrame, LLMMessagesAppendFrame

class LanguageRoutingProcessor(FrameProcessor):
    """
    Analyzes the user's transcribed text to detect language dynamically.
    Instead of changing the entire system prompt, it appends a strict language 
    instruction to the end of the user's message before the LLM processes it.
    """
    def __init__(self, shared_state=None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        self.HINDI_INDICATORS = {
            'hai', 'mujhe', 'kya', 'kaise', 'chahiye', 'mera', 'namaste', 'nahi', 
            'haan', 'ko', 'se', 'mein', 'liye', 'karna', 'kar', 
            'rha', 'rhi', 'hu', 'tha', 'thi', 'sakte', 'bata', 'batao', 'koi'
        }

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        from pipecat.frames.frames import TranscriptionFrame
        
        # We only care about TranscriptionFrame containing user's speech text
        if isinstance(frame, TranscriptionFrame) and frame.text and not frame.user_id == "bot":
            text = frame.text.lower()
            
            # --- Fix Deepgram Time Formatting Bug ---
            # Deepgram smart_format sometimes converts spoken numbers like '708' into
            # timestamps like '07:08' or '7:08'. This is especially disruptive during
            # digit-by-digit phone number entry. Convert ALL time patterns back to digits.
            # E.g. '7:08' -> '708', '07:08' -> '0708', '1:23:45' -> '12345'
            def _collapse_time(m: re.Match) -> str:
                return m.group(0).replace(':', '')
            
            frame.text = re.sub(r'\b\d{1,2}(?::\d{2}){1,2}\b', _collapse_time, frame.text)
            text = frame.text.lower()
            
            # --- Language Detection ---
            # Check for explicit Devanagari script
            devanagari_count = len(re.findall(r'[\u0900-\u097F]', text))
            has_devanagari = devanagari_count > 10
            
            # Check for romanized Hindi words (Hinglish)
            words = set(re.findall(r'\b\w+\b', text))
            hindi_word_count = len(words.intersection(self.HINDI_INDICATORS))
            
            # Force language based on indicators (logged for diagnostic purposes)
            if has_devanagari:
                logger.info(f"Language Detection: Devanagari detected in '{frame.text}'")
            elif hindi_word_count >= 1:
                logger.info(f"Language Detection: Hinglish detected in '{frame.text}'")
            else:
                logger.info(f"Language Detection: English detected in '{frame.text}'")
            
        await self.push_frame(frame, direction)


async def _terminate_plivo_carrier_call(call_id: str, auth_id: str, auth_token: str, session_id: str = "", dispatch_id: str = "", turn_id: int = 0):
    """Hang up the Plivo PSTN call via Plivo REST API with structural non-PII logging."""
    call_uuid_present = bool(call_id)
    if not call_id or not auth_id or not auth_token:
        logger.warning(
            f"[EOC] Missing credentials for Plivo REST hangup | session_id={session_id} | dispatch_id={dispatch_id} | "
            f"turn_id={turn_id} | call_uuid_present={call_uuid_present}"
        )
        return
    endpoint = f"https://api.plivo.com/v1/Account/{auth_id}/Call/{call_id}/"
    logger.info(
        f"[EOC] Invoking Plivo carrier hangup REST API | session_id={session_id} | dispatch_id={dispatch_id} | "
        f"turn_id={turn_id} | call_uuid_present={call_uuid_present}"
    )
    try:
        import aiohttp
        auth = aiohttp.BasicAuth(auth_id, auth_token)
        async with aiohttp.ClientSession() as session:
            async with session.delete(endpoint, auth=auth) as resp:
                status = resp.status
                if status in (200, 204):
                    logger.info(
                        f"[EOC] Plivo REST API call delete success (HTTP {status}) | session_id={session_id} | "
                        f"dispatch_id={dispatch_id} | turn_id={turn_id} | call_uuid_present={call_uuid_present}"
                    )
                else:
                    err_body = await resp.text()
                    logger.error(
                        f"[EOC] Plivo REST API call delete failed (HTTP {status}): {err_body} | "
                        f"session_id={session_id} | dispatch_id={dispatch_id} | turn_id={turn_id} | call_uuid_present={call_uuid_present}"
                    )
    except Exception as e:
        logger.error(
            f"[EOC] Failed to terminate Plivo carrier call via REST API: {e} | session_id={session_id} | "
            f"dispatch_id={dispatch_id} | turn_id={turn_id} | call_uuid_present={call_uuid_present}"
        )


class CallTerminationProcessor(FrameProcessor):
    """
    Monitors conversation completion and triggers graceful call termination.
    Executes:
      1. Plivo carrier call termination via REST API
      2. WebSocket graceful closure
      3. Pipeline task cancellation and cleanup
      4. Watchdog timer to ensure the call ends even if TTS frames are dropped
    """
    def __init__(self, shared_state=None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        self.llm_response_completed = False
        self._hangup_executed = False
        self._watchdog_task = None
        self._current_bot_text = ""

    async def _execute_hangup(self, reason: str = "normal"):
        if self._hangup_executed or self.shared_state.get("termination_started"):
            return
        self._hangup_executed = True
        self.shared_state["termination_started"] = True
        
        session_id = self.shared_state.get("session_id", "unknown")
        dispatch_id = self.shared_state.get("dispatch_id", "unknown")
        turn_id = self.shared_state.get("current_turn_id", 0)
        call_id = self.shared_state.get("call_id") or os.getenv("PLIVO_CALL_ID")
        call_uuid_present = bool(call_id)
        auth_id = self.shared_state.get("auth_id") or os.getenv("PLIVO_AUTH_ID")
        auth_token = self.shared_state.get("auth_token") or os.getenv("PLIVO_AUTH_TOKEN")

        logger.warning(
            f"[EOC] CALL_CLOSING_COMPLETED | termination_reason={reason} | session_id={session_id} | "
            f"dispatch_id={dispatch_id} | turn_id={turn_id} | call_uuid_present={call_uuid_present} | "
            f"termination_started=True"
        )

        # Cancel watchdog timer if running
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        # 1. Terminate Plivo carrier phone call via REST API
        if call_id and auth_id and auth_token:
            asyncio.create_task(
                _terminate_plivo_carrier_call(
                    call_id, auth_id, auth_token,
                    session_id=session_id, dispatch_id=dispatch_id, turn_id=turn_id
                )
            )

        # 2. Allow short 400ms buffer for audio playback to complete on handset
        await asyncio.sleep(0.4)

        # 3. Gracefully close WebSocket
        ws = self.shared_state.get("websocket")
        if ws:
            try:
                from fastapi.websockets import WebSocketState
                if ws.client_state != WebSocketState.DISCONNECTED:
                    logger.info(
                        f"[EOC] Gracefully closing WebSocket connection | session_id={session_id} | "
                        f"dispatch_id={dispatch_id} | call_uuid_present={call_uuid_present}"
                    )
                    await ws.close()
            except Exception as ws_err:
                logger.debug(f"[EOC] WebSocket close notice: {ws_err}")

        # 4. Terminate Pipecat pipeline task
        task = self.shared_state.get("task")
        if task:
            try:
                from pipecat.frames.frames import CancelFrame, EndTaskFrame
                await task.queue_frames([CancelFrame(), EndTaskFrame()])
            except Exception as task_err:
                logger.debug(f"[EOC] Task queue notice: {task_err}")

        self.shared_state["hangup_requested"] = False
        self.shared_state["termination_requested"] = False
        self.shared_state["ending_call"] = False

    async def _start_watchdog(self, timeout_sec: float = 4.5):
        try:
            await asyncio.sleep(timeout_sec)
            if not self._hangup_executed and (self.shared_state.get("hangup_requested") or self.shared_state.get("termination_requested")):
                logger.warning(f"[EOC] Hangup watchdog timeout ({timeout_sec}s) reached. Triggering automatic call termination.")
                await self._execute_hangup(reason="watchdog_timeout")
        except asyncio.CancelledError:
            pass

    def _is_natural_conclusion(self, text: str) -> bool:
        import re
        if "?" in text:
            return False
            
        text_lower = text.lower()
        continuation_markers = [
            "now", "so", "let me", "ask", "question", "confirm", 
            "details", "next", "one more", "another", "what", "how", "why"
        ]
        if any(marker in text_lower for marker in continuation_markers):
            return False
            
        terminal_phrases = [
            "have a great day",
            "have a wonderful day",
            "have a good one",
            "thanks for your time",
            "thank you for your time",
            "appreciate your time",
            "goodbye",
            "bye"
        ]
        if any(phrase in text_lower for phrase in terminal_phrases):
            return True
            
        return False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        from pipecat.frames.frames import (
            TTSStartedFrame, TTSStoppedFrame, EndTaskFrame, TextFrame, AudioRawFrame,
            TranscriptionFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame, CancelFrame,
            BotStartedSpeakingFrame, BotStoppedSpeakingFrame
        )

        # When hangup is first requested, launch safety watchdog timer
        if (self.shared_state.get("hangup_requested") or self.shared_state.get("termination_requested")) and not self._hangup_executed:
            if not self._watchdog_task or self._watchdog_task.done():
                self._watchdog_task = asyncio.create_task(self._start_watchdog(4.5))

        # Reset completed flag when a new user turn starts (unless already in ending_call)
        if isinstance(frame, TranscriptionFrame) and not getattr(frame, 'user_id', None) == "bot":
            if not self.shared_state.get("ending_call"):
                self.llm_response_completed = False
            self._current_bot_text = ""
            
        if isinstance(frame, TextFrame):
            self._current_bot_text += frame.text

        if isinstance(frame, LLMFullResponseEndFrame):
            self.llm_response_completed = True
            # Evaluate for natural conclusion
            if not self.shared_state.get("hangup_requested") and not self.shared_state.get("termination_requested"):
                if self._current_bot_text and self._is_natural_conclusion(self._current_bot_text):
                    logger.warning(f"[EOC] NATURAL CONCLUSION DETECTED | text='{self._current_bot_text}'")
                    self.shared_state["termination_requested"] = True
                    self.shared_state["termination_source"] = "NATURAL_CONCLUSION"
                    if not self._watchdog_task or self._watchdog_task.done():
                        self._watchdog_task = asyncio.create_task(self._start_watchdog(4.5))

        if self.shared_state.get("ending_call") or self.shared_state.get("termination_requested"):
            if isinstance(frame, (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, TTSStartedFrame, TTSStoppedFrame, LLMFullResponseStartFrame)):
                logger.info(
                    "CALL_TERMINATION_FRAME",
                    frame_type=type(frame).__name__,
                    ending_call=self.shared_state.get("ending_call"),
                    termination_requested=self.shared_state.get("termination_requested"),
                    ending_call_turn_id=self.shared_state.get("ending_call_turn_id"),
                )

        if not isinstance(frame, (AudioRawFrame, TextFrame)):
            logger.debug(f"CallTerminationProcessor received: {type(frame).__name__} | hangup_requested={self.shared_state.get('hangup_requested', False)} | termination_requested={self.shared_state.get('termination_requested', False)}")

        await self.push_frame(frame, direction)

        if isinstance(frame, BotStoppedSpeakingFrame):
            logger.info(f"[EOC] CallTerminationProcessor saw BotStoppedSpeakingFrame. state: {self.shared_state}")
            if self.shared_state.get("hangup_requested") or self.shared_state.get("termination_requested"):
                await self._execute_hangup(reason="bot_goodbye_completed")
