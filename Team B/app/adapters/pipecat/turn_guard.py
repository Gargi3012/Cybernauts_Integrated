"""
TurnGuard — Stale-response cancellation and turn-id management.

Problem: When the user speaks multiple times in rapid succession, multiple
LLM requests can be in-flight simultaneously. If an older LLM response
finishes *after* a newer user turn has started, its audio would play on
top of the new conversation turn, producing confusing overlapping speech.

Solution: A monotonically-incrementing `turn_id` is stamped on every
LLMContextFrame.  If a LLMFullResponseStartFrame arrives for a turn_id
that is older than the current turn, the entire response (all TextFrames
and downstream audio) is suppressed until the next valid LLMFullResponseStartFrame.

Architecture notes:
  - Placed in pipeline between user_agg and LLM (upstream side).
  - Also placed between LLM output and TTS (downstream side) via the same
    shared `_current_turn` counter, inspected by a companion filter.
  - Uses shared_state so CallTerminationProcessor can also read turn state.
"""

import asyncio
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMRunFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
)


class TurnGuardProcessor(FrameProcessor):
    """
    Injects a turn_id into every LLMContextFrame and discards stale
    LLM responses (TextFrame / TTSStartedFrame / TTSStoppedFrame chains)
    that belong to a superseded turn.

    Place this processor BEFORE the LLM in the pipeline.
    A companion TurnGuardFilter (same shared state) sits AFTER the LLM.
    """

    def __init__(self, shared_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        # Start at 0 — incremented on every new user context frame
        self.shared_state.setdefault("current_turn_id", 0)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMContextFrame, LLMRunFrame)):
            # New user turn — bump the counter
            self.shared_state["current_turn_id"] += 1
            turn_id = self.shared_state["current_turn_id"]
            # Stamp the frame so downstream filter knows which turn this is
            frame._turn_id = turn_id  # type: ignore[attr-defined]
            logger.info(
                f"[TURN] New turn_id={turn_id} stamped on {type(frame).__name__}"
            )

        elif isinstance(frame, UserStartedSpeakingFrame):
            # User started speaking — the current in-flight LLM response (if any)
            # is now stale once a new transcript arrives.  We don't bump turn_id
            # here yet because we wait for the TranscriptionFrame / LLMContextFrame,
            # but we record that new speech is starting.
            logger.debug("[TURN] UserStartedSpeaking — next LLMContextFrame will bump turn_id")

        await self.push_frame(frame, direction)


class TurnGuardFilter(FrameProcessor):
    """
    Sits AFTER the LLM (between LLM and TTS).  Suppresses TextFrames and
    TTS frames that belong to a stale turn_id.

    When a LLMFullResponseStartFrame arrives:
      - Read its _turn_id attribute (stamped by TurnGuardProcessor).
      - Compare against shared_state["current_turn_id"].
      - If older → mark _suppressing = True and discard until LLMFullResponseEndFrame.
      - If current → pass through normally.

    This prevents old queued audio from playing after new user speech.
    """

    def __init__(self, shared_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        self._suppressing = False
        self._suppressed_turn_id = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # --- Check if ENDING_CALL — block new LLM responses ---
        if self.shared_state.get("ending_call"):
            ending_turn_id = self.shared_state.get("ending_call_turn_id")
            current_turn_id = self.shared_state.get("current_turn_id", 0)
            
            # If ending_call was just set in this turn, allow it to generate the final goodbye
            if ending_turn_id is None or current_turn_id > ending_turn_id:
                if isinstance(frame, (LLMFullResponseStartFrame, TextFrame,
                                      TTSStartedFrame, TTSStoppedFrame,
                                      LLMFullResponseEndFrame)):
                    logger.info(
                        f"[TURN] ENDING_CALL: suppressing {type(frame).__name__} for subsequent turn {current_turn_id}"
                    )
                    # Still push LLMFullResponseEndFrame so aggregators don't get stuck
                    if isinstance(frame, LLMFullResponseEndFrame):
                        await self.push_frame(frame, direction)
                    return
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            frame_turn_id = getattr(frame, "_turn_id", None)
            current_turn_id = self.shared_state.get("current_turn_id", 0)

            if frame_turn_id is not None and frame_turn_id < current_turn_id:
                self._suppressing = True
                self._suppressed_turn_id = frame_turn_id
                logger.warning(
                    f"[TURN] STALE response turn_id={frame_turn_id} < "
                    f"current_turn_id={current_turn_id} — suppressing"
                )
                self.shared_state["stale_responses_discarded"] = (
                    self.shared_state.get("stale_responses_discarded", 0) + 1
                )
                return  # swallow the StartFrame entirely
            else:
                self._suppressing = False
                self._suppressed_turn_id = None
                logger.debug(
                    f"[TURN] Valid response turn_id={frame_turn_id} passing through"
                )

        elif isinstance(frame, LLMFullResponseEndFrame) and self._suppressing:
            logger.warning(
                f"[TURN] STALE_RESPONSE_DISCARDED | turn_id={self._suppressed_turn_id}"
            )
            logger.warning(
                f"[FILLER] FILLER_DISCARDED_AS_STALE | turn_id={self._suppressed_turn_id}"
            )
            self._suppressing = False
            self._suppressed_turn_id = None
            await self.push_frame(frame, direction)  # End frame must pass so aggregator doesn't stall
            return

        elif self._suppressing and isinstance(frame, (TextFrame, TTSStartedFrame, TTSStoppedFrame)):
            if getattr(frame, "is_filler", False):
                logger.warning(
                    f"[FILLER] FILLER_DISCARDED_AS_STALE | turn_id={self._suppressed_turn_id}"
                )
            # Drop stale audio/text frames
            return

        await self.push_frame(frame, direction)


from typing import Optional, Any

try:
    from pipecat.turns.user_start.base_user_turn_start_strategy import BaseUserTurnStartStrategy
    from pipecat.turns.user_stop import BaseUserTurnStopStrategy, UserTurnStoppedParams
    from pipecat.turns.types import ProcessFrameResult
    from pipecat.frames.frames import (
        InterimTranscriptionFrame,
        TranscriptionFrame,
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
        UserSpeakingFrame,
    )
except ImportError:
    BaseUserTurnStartStrategy = object
    BaseUserTurnStopStrategy = object
    ProcessFrameResult = None
    UserTurnStoppedParams = None
    InterimTranscriptionFrame = object
    TranscriptionFrame = object
    VADUserStartedSpeakingFrame = object
    VADUserStoppedSpeakingFrame = object
    UserSpeakingFrame = object


class ValidatedUserTurnStartStrategy(BaseUserTurnStartStrategy):
    """
    Validates user speech before triggering an interruption.

    Prevents false VAD triggers (breaths, clicks, ambient noise) from
    prematurely cancelling active LLM generation or TTS output.

    Interruption is triggered ONLY when:
    1. A real STT transcript arrives (InterimTranscriptionFrame or TranscriptionFrame)
       with at least 1 word (e.g. 'Wait', 'No', 'Ruko', 'Ek minute', etc.).
    OR
    2. Sustained speech activity persists for at least `min_speech_duration` (e.g. 0.25s).
    """

    def __init__(
        self,
        min_speech_duration: float = 0.25,
        shared_state: Optional[dict] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.min_speech_duration = min_speech_duration
        self.shared_state = shared_state if shared_state is not None else {}
        self._speech_start_time: Optional[float] = None
        self._is_speaking_vad = False
        self._triggered = False

    async def reset(self):
        await super().reset()
        self._speech_start_time = None
        self._is_speaking_vad = False
        self._triggered = False

    async def process_frame(self, frame: Frame) -> Any:
        import time
        now = time.perf_counter()

        # 1. Transcript evidence (Instant Barge-in)
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            text = (getattr(frame, "text", "") or "").strip()
            import re
            clean_text = re.sub(r'\[System:.*?\]', '', text).strip()
            if clean_text and not getattr(frame, "user_id", None) == "bot":
                turn_id = self.shared_state.get("current_turn_id", 0)
                logger.info(
                    f"[INTERRUPTION_DIAGNOSTICS] VAD_INTERRUPTION_ACCEPTED | "
                    f"turn_id={turn_id} | reason=transcript | text='{clean_text}'"
                )
                self._triggered = True
                await self.trigger_user_turn_started()
                return ProcessFrameResult.STOP if ProcessFrameResult else None

        # 2. VAD speech start
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self._is_speaking_vad = True
            self._speech_start_time = now
            turn_id = self.shared_state.get("current_turn_id", 0)
            logger.info(
                f"[INTERRUPTION_DIAGNOSTICS] VAD_SPEECH_START | "
                f"turn_id={turn_id} | timestamp={now:.3f}"
            )
            return ProcessFrameResult.CONTINUE if ProcessFrameResult else None

        # 3. Speech activity (check duration)
        elif isinstance(frame, UserSpeakingFrame) and self._is_speaking_vad and self._speech_start_time:
            duration = now - self._speech_start_time
            if duration >= self.min_speech_duration and not self._triggered:
                turn_id = self.shared_state.get("current_turn_id", 0)
                logger.info(
                    f"[INTERRUPTION_DIAGNOSTICS] VAD_INTERRUPTION_ACCEPTED | "
                    f"turn_id={turn_id} | reason=sustained_speech | duration={duration:.3f}s"
                )
                self._triggered = True
                await self.trigger_user_turn_started()
                return ProcessFrameResult.STOP if ProcessFrameResult else None

        # 4. VAD speech stopped
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            if self._speech_start_time and not self._triggered:
                duration = now - self._speech_start_time
                turn_id = self.shared_state.get("current_turn_id", 0)
                if duration < self.min_speech_duration:
                    logger.info(
                        f"[INTERRUPTION_DIAGNOSTICS] VAD_SHORT_NOISE_IGNORED | "
                        f"turn_id={turn_id} | duration={duration:.3f}s"
                    )
                else:
                    logger.info(
                        f"[INTERRUPTION_DIAGNOSTICS] VAD_INTERRUPTION_REJECTED | "
                        f"turn_id={turn_id} | reason=stopped_before_confirmation | duration={duration:.3f}s"
                    )
            self._is_speaking_vad = False
            self._speech_start_time = None

        return ProcessFrameResult.CONTINUE if ProcessFrameResult else None


class OptimizedUserTurnStopStrategy(BaseUserTurnStopStrategy):
    """
    Optimized user turn stop strategy with deterministic phone capture support.

    Architecture:
    1. Silence-Aware Timing: When VAD declares user stopped speaking (after stop_secs),
       the strategy accounts for the fact that stop_secs of silence have ALREADY elapsed.
    2. Phone Digit Recognition & Dynamic Pause Extension:
       - Detects when phone digits are being spoken or PHONE_CAPTURE state is active.
       - Extends silence timeout to 2.2s for partial digits (<10 digits), allowing
         callers to speak digits at a natural pace without premature LLM interruption.
       - Reduces timeout to 0.15s (immediate finalization) as soon as 10 valid digits
         or an explicit final phrase ("that's my number") is confirmed.
    3. Transcript Deduplication & Revision:
       - Detects duplicate STT frames and revised hypothesis expansions from Deepgram.
       - Commits only finalized, deduplicated segments without duplicate token appending.
    4. Diagnostic Logging:
       - Safe, non-PII diagnostic logging for PHONE_CAPTURE turns (<REDACTED_NUMERIC>).
    """

    def __init__(
        self,
        user_speech_timeout: float = 0.45,
        digit_speech_timeout: float = 2.2,
        digit_complete_timeout: float = 0.15,
        shared_state: Optional[dict] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.user_speech_timeout = user_speech_timeout
        self.digit_speech_timeout = digit_speech_timeout
        self.digit_complete_timeout = digit_complete_timeout
        self.shared_state = shared_state if shared_state is not None else {}
        self._text = ""
        self._last_final_text: str = ""
        self._vad_user_speaking = False
        self._transcript_finalized = False
        self._speech_end_estimate: Optional[float] = None
        self._turn_stopped_emitted = False
        self._timeout_task: Optional[asyncio.Task] = None

    async def reset(self):
        await super().reset()
        self._text = ""
        self._last_final_text = ""
        self._vad_user_speaking = False
        self._transcript_finalized = False
        self._speech_end_estimate = None
        self._turn_stopped_emitted = False
        if self._timeout_task:
            try:
                self._timeout_task.cancel()
            except Exception:
                pass
            self._timeout_task = None

    async def cleanup(self):
        await super().cleanup()
        if self._timeout_task:
            try:
                self._timeout_task.cancel()
            except Exception:
                pass
            self._timeout_task = None

    def _get_active_speech_timeout(self) -> float:
        """
        Determines the dynamic speech silence timeout.
        Returns digit_complete_timeout (0.15s) when 10 digits are valid or final phrase spoken,
        digit_speech_timeout (2.2s) when partial digits are being accumulated during PHONE_CAPTURE,
        or user_speech_timeout (0.45s) for normal conversation.
        """
        phone_norm = self.shared_state.get("phone_normalizer")
        phone_confirmed = self.shared_state.get("phone_confirmed", False)
        
        in_phone_capture = phone_norm and len(phone_norm.digits) > 0 and not phone_confirmed

        if not in_phone_capture:
            return self.user_speech_timeout

        from app.services.phone_digit_normalizer import (
            PhoneDigitNormalizer,
            is_valid_indian_mobile,
            TokenType,
        )

        has_final_phrase = PhoneDigitNormalizer.detect_final_phrase(self._text) if self._text else False

        total_digits = ""
        if phone_norm and hasattr(phone_norm, "digits"):
            total_digits = phone_norm.digits
        elif self._text:
            cands = PhoneDigitNormalizer.extract_turn_candidates(self._text)
            if cands and cands[0]:
                total_digits = cands[0]

        if has_final_phrase or (len(total_digits) == 10 and is_valid_indian_mobile(total_digits)):
            return self.digit_complete_timeout

        if 0 < len(total_digits) < 10:
            return self.digit_speech_timeout

        return self.user_speech_timeout

    async def process_frame(self, frame: Frame) -> Any:
        import time
        now = time.perf_counter()

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._vad_user_speaking = True
            self._speech_end_estimate = None
            self._transcript_finalized = False
            if self._timeout_task:
                try:
                    self._timeout_task.cancel()
                except Exception:
                    pass
                self._timeout_task = None
            return ProcessFrameResult.CONTINUE if ProcessFrameResult else None

        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._vad_user_speaking = False
            stop_secs = getattr(frame, "stop_secs", 0.0) or 0.4
            self._speech_end_estimate = now - stop_secs
            active_timeout = self._get_active_speech_timeout()

            # If we already have finalized transcript text, evaluate immediate finalization
            if self._text.strip() and self._transcript_finalized:
                elapsed_silence = now - self._speech_end_estimate
                if elapsed_silence >= active_timeout:
                    await self._maybe_trigger_user_turn_stopped()
                    return ProcessFrameResult.CONTINUE if ProcessFrameResult else None
                else:
                    remaining = max(0.01, active_timeout - elapsed_silence)
                    self._schedule_timeout(remaining)
            elif self._text.strip():
                # Waiting for final transcript; schedule fallback timeout
                self._schedule_timeout(active_timeout)

            return ProcessFrameResult.CONTINUE if ProcessFrameResult else None

        elif isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", "") or "").strip()
            # Ignore bot echo / system instructions
            if text and not getattr(frame, "user_id", None) == "bot":
                import re
                clean_text = re.sub(r'\[System:.*?\]', '', text).strip()
                if clean_text:
                    from app.services.phone_digit_normalizer import (
                        PhoneDigitNormalizer,
                        log_deepgram_diagnostic_event,
                        TokenType,
                    )

                    # Deduplication & hypothesis revision
                    segment_type = "final"
                    if clean_text == self._last_final_text:
                        segment_type = "duplicate"
                    elif self._text and clean_text.startswith(self._text):
                        self._text = clean_text
                        segment_type = "revised_expansion"
                    elif self._text and self._text.endswith(clean_text):
                        segment_type = "duplicate_subset"
                    else:
                        overlap = PhoneDigitNormalizer._find_overlap(self._text, clean_text)
                        if overlap > 0:
                            self._text += clean_text[overlap:]
                            segment_type = "overlap_merged"
                        else:
                            self._text = (self._text + " " + clean_text) if self._text else clean_text
                            segment_type = "continuation"

                    self._last_final_text = clean_text
                    self._transcript_finalized = True

                    # Check phone capture state & update normalizer if present
                    turn_id = self.shared_state.get("current_turn_id", 0)
                    session_id = self.shared_state.get("session_id", "")
                    phone_norm = self.shared_state.get("phone_normalizer")
                    tokens = PhoneDigitNormalizer.extract_tokens(clean_text)
                    has_digit_tokens = any(
                        t.token_type in (TokenType.DIGIT, TokenType.MULTIPLIER, TokenType.TIME_LIKE_AMBIGUOUS)
                        for t in tokens
                    )

                    if phone_norm:
                        in_phone_capture = len(phone_norm.digits) > 0 and not self.shared_state.get("phone_confirmed", False)
                        # Also enter phone capture if we see digit tokens
                        if not in_phone_capture and has_digit_tokens:
                            in_phone_capture = True
                            
                        if in_phone_capture:
                            buf_before = phone_norm.digits if phone_norm else ""
                            if phone_norm and segment_type != "duplicate":
                                phone_norm.process_utterance(clean_text)
                            buf_after = phone_norm.digits if phone_norm else ""
                            status_val = phone_norm.status.value if phone_norm else "collecting"

                            speech_final = bool(getattr(frame, "speech_final", False))
                            log_deepgram_diagnostic_event(
                                session_id=session_id,
                                turn_id=turn_id,
                                transcript=clean_text,
                                is_final=True,
                                speech_final=speech_final,
                                confidence=float(getattr(frame, "confidence", 1.0) or 1.0),
                                words=getattr(frame, "words", None),
                                segment_type=segment_type,
                                buffer_before=buf_before,
                                buffer_after=buf_after,
                                validation_status=status_val,
                            )

                    active_timeout = self._get_active_speech_timeout()

                    # If user is not speaking according to VAD, check if we can finalize
                    if not self._vad_user_speaking and self._speech_end_estimate:
                        elapsed_silence = now - self._speech_end_estimate
                        if elapsed_silence >= active_timeout:
                            await self._maybe_trigger_user_turn_stopped()
                            return ProcessFrameResult.CONTINUE if ProcessFrameResult else None
                        else:
                            remaining = max(0.01, active_timeout - elapsed_silence)
                            self._schedule_timeout(remaining)
                    elif not self._vad_user_speaking and self._speech_end_estimate is None:
                        # Fallback when transcripts arrive without VAD stop
                        self._schedule_timeout(active_timeout)

            return ProcessFrameResult.CONTINUE if ProcessFrameResult else None

        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim transcript indicates user is still actively speaking
            if self._timeout_task:
                try:
                    self._timeout_task.cancel()
                except Exception:
                    pass
                self._timeout_task = None

            text = (getattr(frame, "text", "") or "").strip()
            if text and not getattr(frame, "user_id", None) == "bot":
                import re
                clean_text = re.sub(r'\[System:.*?\]', '', text).strip()
                phone_norm = self.shared_state.get("phone_normalizer")
                in_phone_capture = False
                if phone_norm:
                    in_phone_capture = len(phone_norm.digits) > 0 and not self.shared_state.get("phone_confirmed", False)
                    # Also check for digits in the interim transcript
                    if not in_phone_capture:
                        from app.services.phone_digit_normalizer import PhoneDigitNormalizer, TokenType
                        tokens = PhoneDigitNormalizer.extract_tokens(clean_text)
                        has_digit_tokens = any(t.token_type in (TokenType.DIGIT, TokenType.MULTIPLIER, TokenType.TIME_LIKE_AMBIGUOUS) for t in tokens)
                        if has_digit_tokens:
                            in_phone_capture = True
                            
                if in_phone_capture:
                    from app.services.phone_digit_normalizer import log_deepgram_diagnostic_event
                    turn_id = self.shared_state.get("current_turn_id", 0)
                    session_id = self.shared_state.get("session_id", "")
                    buf = phone_norm.digits if phone_norm else ""
                    log_deepgram_diagnostic_event(
                        session_id=session_id,
                        turn_id=turn_id,
                        transcript=clean_text,
                        is_final=False,
                        speech_final=False,
                        confidence=float(getattr(frame, "confidence", 1.0) or 1.0),
                        words=getattr(frame, "words", None),
                        segment_type="interim",
                        buffer_before=buf,
                        buffer_after=buf,
                        validation_status="interim_hypothesis",
                    )

            return ProcessFrameResult.CONTINUE if ProcessFrameResult else None

        return ProcessFrameResult.CONTINUE if ProcessFrameResult else None

    def _schedule_timeout(self, timeout_secs: float):
        if self._timeout_task:
            try:
                self._timeout_task.cancel()
            except Exception:
                pass
        loop = asyncio.get_running_loop()
        self._timeout_task = loop.create_task(self._timeout_handler(timeout_secs))

    async def _timeout_handler(self, timeout_secs: float):
        try:
            await asyncio.sleep(timeout_secs)
            await self._maybe_trigger_user_turn_stopped()
        except asyncio.CancelledError:
            pass
        finally:
            self._timeout_task = None

    async def _maybe_trigger_user_turn_stopped(self):
        if self._turn_stopped_emitted:
            return
        if self._vad_user_speaking:
            return
        if not self._text.strip():
            return
        self._turn_stopped_emitted = True
        if self._timeout_task:
            try:
                self._timeout_task.cancel()
            except Exception:
                pass
            self._timeout_task = None
        turn_id = self.shared_state.get("current_turn_id", 0)
        active_timeout = self._get_active_speech_timeout()
        logger.info(
            f"[END_OF_TURN] User turn finalized | turn_id={turn_id} | "
            f"text='{self._text.strip()}' | speech_timeout={active_timeout}s"
        )
        await self.trigger_user_turn_stopped()


