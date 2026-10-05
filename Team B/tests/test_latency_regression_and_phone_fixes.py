"""
test_latency_regression_and_phone_fixes.py
=========================================
Deterministic regression test suite for:
- Root cause #1: Internal greeting instruction digit leakage & phone timeout activation
- Issue #2: Weak interim STT noise triggering premature TTS barge-in
- Explicit PHONE_CAPTURE state transitions
- Audio completeness & termination isolation
"""

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock
import pytest

from pipecat.frames.frames import (
    TranscriptionFrame,
    InterimTranscriptionFrame,
    BotStoppedSpeakingFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
)
from pipecat.turns.types import ProcessFrameResult

from app.adapters.pipecat.context_manager import (
    CriticalCallMemory,
    SlidingWindowLLMContext,
)
from app.adapters.pipecat.turn_guard import (
    OptimizedUserTurnStopStrategy,
    ValidatedUserTurnStartStrategy,
    TurnGuardFilter,
)
from app.adapters.pipecat.end_call_detector import SemanticEndCallDetector
from app.adapters.pipecat.language_router import CallTerminationProcessor
from app.adapters.pipecat.sarvam_tts_service import LowLatencyClauseAggregator
from app.services.phone_digit_normalizer import mask_phone_number


class TestLatencyRegressionAndPhoneFixes:
    """Verifies all 11 requirements specified in FIX #13."""

    def test_1_internal_greeting_does_not_populate_phone_buffer(self):
        """
        TEST 1 — INTERNAL GREETING DOES NOT POPULATE PHONE BUFFER
        Inject the real internal greeting instruction.
        Expected:
            phone_buffer.digits == empty
            phone_capture == False
            no phone state mutation
        """
        shared_state = {}
        ctx = SlidingWindowLLMContext(
            session_id="sess_test_1",
            max_window_messages=8,
            shared_state=shared_state,
        )

        internal_greeting_msg = {
            "role": "user",
            "content": (
                "The phone call has just connected to the recipient (Rahul Manchanda at Cybernauts Technologies). "
                "Deliver your opening greeting now, strictly following the call script, persona, and greeting instructions specified in your system instructions. "
                "Make it a natural, polite, and concise opening turn (1-2 sentences). Do not read the entire script at once."
            ),
            "source": "INTERNAL_GREETING",
            "is_internal_instruction": True,
        }

        ctx.add_message(internal_greeting_msg)

        # Phone digits must be completely empty
        assert ctx.critical_memory.phone_digits == ""
        assert shared_state.get("in_phone_capture") is False
        assert shared_state.get("phone_confirmed") is False
        phone_norm = shared_state.get("phone_normalizer")
        assert phone_norm is not None
        assert phone_norm.digits == ""

    @pytest.mark.asyncio
    async def test_2_normal_conversation_uses_450ms(self):
        """
        TEST 2 — NORMAL CONVERSATION USES 450ms
        Start a call.
        Inject internal greeting.
        Then user says: "क्या काम से आपने call करा है मुझे?"
        Expected:
            phone capture inactive
            speech timeout = 0.45s
        """
        shared_state = {}
        ctx = SlidingWindowLLMContext(
            session_id="sess_test_2",
            max_window_messages=8,
            shared_state=shared_state,
        )

        # Inject internal greeting instruction
        ctx.add_message({
            "role": "user",
            "content": "The phone call has just connected to the recipient. (1-2 sentences).",
            "source": "INTERNAL_GREETING",
            "is_internal_instruction": True,
        })

        # User speaks conversational turn
        user_utterance = "क्या काम से आपने call करा है मुझे?"
        ctx.add_message({
            "role": "user",
            "content": user_utterance,
            "source": "USER_SPEECH",
        })

        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )
        await strategy.process_frame(TranscriptionFrame(text=user_utterance, user_id="user", timestamp="2026-10-05T00:00:00Z"))

        assert shared_state.get("in_phone_capture") is False
        timeout = strategy._get_active_speech_timeout()
        assert timeout == 0.45, f"Expected 0.45s conversational timeout, got {timeout}s"

    @pytest.mark.asyncio
    async def test_3_normal_hinglish_conversation(self):
        """
        TEST 3 — NORMAL HINGLISH CONVERSATION
        User: "Manually handle होते हैं."
        Expected:
            0.45s normal timeout
        """
        shared_state = {"in_phone_capture": False}
        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )

        utterance = "Manually handle होते हैं."
        await strategy.process_frame(TranscriptionFrame(text=utterance, user_id="user", timestamp="2026-10-05T00:00:00Z"))

        timeout = strategy._get_active_speech_timeout()
        assert timeout == 0.45, f"Expected 0.45s normal timeout, got {timeout}s"

    @pytest.mark.asyncio
    async def test_4_actual_phone_capture(self):
        """
        TEST 4 — ACTUAL PHONE CAPTURE
        AI explicitly requests phone number.
        User: 9 2 1 5 0 2 4 4 0 1
        Expected:
            PHONE_CAPTURE = True
            digits accumulate correctly
            10 digits detected
            complete timeout = 0.15s
            normal conversation timeout restored afterward upon confirmation
        """
        shared_state = {}
        ctx = SlidingWindowLLMContext(
            session_id="sess_test_4",
            max_window_messages=8,
            shared_state=shared_state,
        )

        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )

        # 1. AI explicitly asks for mobile number
        ctx.add_message({
            "role": "assistant",
            "content": "अपना 10-digit mobile number digit-by-digit बताइए।",
        })

        assert shared_state.get("in_phone_capture") is True

        # 2. User speaks 10 digits
        digits_text = "9 2 1 5 0 2 4 4 0 1"
        await strategy.process_frame(TranscriptionFrame(text=digits_text, user_id="user", timestamp="2026-10-05T00:00:00Z"))
        ctx.add_message({
            "role": "user",
            "content": digits_text,
            "source": "USER_SPEECH",
        })

        assert ctx.critical_memory.phone_digits == "9215024401"
        assert len(ctx.critical_memory.phone_digits) == 10
        timeout = strategy._get_active_speech_timeout()
        assert timeout == 0.15, f"Expected complete 0.15s timeout, got {timeout}s"

        # 3. AI confirms readback and user confirms
        ctx.add_message({
            "role": "assistant",
            "content": "Just to confirm, your number is 9 2 1 5 0 2 4 4 0 1—is that correct?",
        })
        ctx.add_message({
            "role": "user",
            "content": "हाँ, मेरा number सही है.",
            "source": "USER_SPEECH",
        })

        assert ctx.critical_memory.phone_confirmed is True
        assert shared_state.get("in_phone_capture") is False

        # Timeout should return to conversational 0.45s
        await strategy.process_frame(TranscriptionFrame(text="Great thank you", user_id="user", timestamp="2026-10-05T00:00:00Z"))
        normal_timeout = strategy._get_active_speech_timeout()
        assert normal_timeout == 0.45, f"Expected timeout to revert to 0.45s, got {normal_timeout}s"

    @pytest.mark.asyncio
    async def test_5_internal_numbers_do_not_activate_phone_capture(self):
        """
        TEST 5 — INTERNAL NUMBERS DO NOT ACTIVATE PHONE CAPTURE
        Inject text containing:
            1-2 sentences
            company years
            prices
            dates
            IDs
        Expected:
            no phone buffer mutation
            no 2.2s timeout
        """
        shared_state = {}
        ctx = SlidingWindowLLMContext(
            session_id="sess_test_5",
            max_window_messages=8,
            shared_state=shared_state,
        )

        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )

        test_phrases = [
            "Please deliver your answer in 1-2 sentences.",
            "Our company was founded 15 years ago in 2009.",
            "The enterprise tier price is $1,500/mo.",
            "Our kickoff meeting is on 2026-10-05.",
            "Support ticket ID is #4891.",
        ]

        for phrase in test_phrases:
            ctx.add_message({
                "role": "user",
                "content": phrase,
                "source": "USER_SPEECH",
            })
            await strategy.process_frame(TranscriptionFrame(text=phrase, user_id="user", timestamp="2026-10-05T00:00:00Z"))

            assert ctx.critical_memory.phone_digits == "", f"Phone digits polluted by phrase: '{phrase}'"
            assert shared_state.get("in_phone_capture") is False
            timeout = strategy._get_active_speech_timeout()
            assert timeout == 0.45, f"Timeout incorrectly set to {timeout}s for phrase: '{phrase}'"

    @pytest.mark.asyncio
    async def test_6_phone_confirmation_is_not_interrupted_by_weak_interim(self):
        """
        TEST 6 — PHONE CONFIRMATION IS NOT INTERRUPTED
        Simulate:
            Agent TTS: "Just to confirm, your number is 9 2 1 5 0 2 4 4 0 1..."
        Simulate a weak Deepgram interim fragment:
            "You"
        Expected:
            no interruption
            no Cartesia cancellation
            all logical TTS chunks continue
        """
        shared_state = {"tts_speaking": True, "current_turn_id": 5}
        start_strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
        turn_started_events = []
        start_strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        # Deepgram interim produces weak fragment "You"
        interim_frame = InterimTranscriptionFrame(text="You", user_id="user", timestamp="2026-10-05T00:00:00Z")
        res = await start_strategy.process_frame(interim_frame)

        assert res != ProcessFrameResult.STOP, "Interim noise 'You' must NOT stop frame processing"
        assert len(turn_started_events) == 0, "Interim noise 'You' must NOT trigger turn started"

    @pytest.mark.asyncio
    async def test_7_real_barge_in_still_works(self):
        """
        TEST 7 — REAL BARGE-IN STILL WORKS
        Agent speaking.
        User says: "रुकिए"
        Expected:
            interruption
            TTS cancellation
            next user turn accepted
        """
        shared_state = {"tts_speaking": True, "current_turn_id": 5}
        start_strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
        turn_started_events = []
        start_strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        # User speaks legitimate interruption word
        frame = TranscriptionFrame(text="रुकिए", user_id="user", timestamp="2026-10-05T00:00:00Z")
        res = await start_strategy.process_frame(frame)

        assert res == ProcessFrameResult.STOP, "'रुकिए' must trigger immediate turn stop"
        assert len(turn_started_events) == 1, "'रुकिए' must trigger turn started event"

    @pytest.mark.asyncio
    async def test_8_phone_confirmation_audio_completeness(self):
        """
        TEST 8 — PHONE CONFIRMATION AUDIO COMPLETENESS
        Verify that every logical text chunk reaches TTS.
        Track structurally:
            turn_id
            chunk index
            chunk count
            text length
            digit-token count
        Do not log the actual phone number.
        Expected:
            all chunks accepted
        """
        aggregator = LowLatencyClauseAggregator()
        full_text = "Just to confirm, your number is 9 2 1 5 0 2 4 4 0 1—is that correct?"

        # Stream token by token
        emitted_chunks = []
        tokens = ["Just ", "to ", "confirm, ", "your ", "number ", "is ", "9 ", "2 ", "1 ", "5 ", "0 ", "2 ", "4 ", "4 ", "0 ", "1—", "is ", "that ", "correct?"]
        for tok in tokens:
            async for chunk in aggregator.aggregate(tok):
                emitted_chunks.append(chunk.text)
        rem = await aggregator.flush()
        if rem:
            emitted_chunks.append(rem.text)

        # Structural verification
        structural_audit = []
        for idx, chunk in enumerate(emitted_chunks):
            digits = re.findall(r'\d', chunk)
            structural_audit.append({
                "chunk_idx": idx,
                "length": len(chunk),
                "digit_count": len(digits),
                "has_terminal_punct": chunk[-1] in ",.!?—",
            })

        # Ensure all words from full_text are preserved
        combined_emitted = " ".join(emitted_chunks)
        clean_emitted = re.sub(r'[^\w]', '', combined_emitted)
        clean_original = re.sub(r'[^\w]', '', full_text)
        assert clean_emitted == clean_original, f"Mismatch in emitted text: '{combined_emitted}' vs '{full_text}'"
        assert len(emitted_chunks) >= 3, f"Expected incremental streaming, got {len(emitted_chunks)} chunks"

    @pytest.mark.asyncio
    async def test_9_no_termination_during_phone_confirmation(self):
        """
        TEST 9 — NO TERMINATION DURING PHONE CONFIRMATION
        Expected:
            termination_requested == False
        unless an independent explicit goodbye/end-call signal occurs.
        """
        shared_state = {}
        detector = SemanticEndCallDetector(shared_state=shared_state)

        phone_confirmation_utterances = [
            "9 2 1 5 0 2 4 4 0 1",
            "हाँ, मेरा number सही है.",
            "Yes, that is my number.",
            "Correct.",
        ]

        for text in phone_confirmation_utterances:
            await detector.process_frame(TranscriptionFrame(text=text, user_id="user", timestamp="2026-10-05T00:00:00Z"), None)
            assert shared_state.get("ending_call") is not True, f"Erroneous termination on '{text}'"
            assert shared_state.get("hangup_requested") is not True, f"Erroneous hangup on '{text}'"

    @pytest.mark.asyncio
    async def test_10_goodbye_still_terminates(self):
        """
        TEST 10 — GOODBYE STILL TERMINATES
        User: "Okay, thank you. Bye bye."
        Expected:
            SemanticEndCallDetector
            → termination state
            → final goodbye
            → BotStoppedSpeakingFrame
            → one hangup
        """
        from unittest.mock import patch
        with patch("app.adapters.pipecat.language_router._terminate_plivo_carrier_call", new_callable=AsyncMock) as mock_hangup:
            shared_state = {
                "call_id": "test_plivo_uuid",
                "auth_id": "test_auth",
                "auth_token": "test_token",
            }
            detector = SemanticEndCallDetector(shared_state=shared_state)
            terminator = CallTerminationProcessor(
                session_id="sess_test_10",
                shared_state=shared_state,
            )

            # 1. User says goodbye
            await detector.process_frame(TranscriptionFrame(text="Okay, thank you. Bye bye.", user_id="user", timestamp="2026-10-05T00:00:00Z"), None)
            assert shared_state.get("ending_call") is True
            assert shared_state.get("hangup_requested") is True

            # 2. Bot finishes speaking final goodbye
            await terminator.process_frame(BotStoppedSpeakingFrame(), None)
            await asyncio.sleep(0.05)

            assert shared_state.get("termination_started") is True
            assert mock_hangup.call_count == 1, f"Expected exactly 1 hangup call, got {mock_hangup.call_count}"

    @pytest.mark.asyncio
    async def test_11_normal_thank_you_does_not_terminate(self):
        """
        TEST 11 — NORMAL THANK-YOU DOES NOT TERMINATE
        Agent: "Thank you for confirming your number."
        Expected:
            call continues
        """
        shared_state = {}
        detector = SemanticEndCallDetector(shared_state=shared_state)

        # Agent statement or polite user response
        await detector.process_frame(TranscriptionFrame(text="Thank you for confirming your number.", user_id="assistant", timestamp="2026-10-05T00:00:00Z"), None)
        assert shared_state.get("ending_call") is not True
        assert shared_state.get("hangup_requested") is not True
