"""
test_deepgram_phone_capture_regression.py — Production Failure Regression & Deterministic Capture Suite
======================================================================================================
Tests:
1. Exact production failure reproduction:
   "राहुल and मेरा phone number है 921 05:02 4 04:01."
   Followed by sequential chunks: "921", "5", "0", "2", "4 04:01", "0 1".
2. Preservation of persistent phone buffer across multiple turns without reset.
3. Strict prevention of double-counting between interim and final transcripts.
4. Time-like token safety: "05:02" and "04:01" are classified as TIME_LIKE_AMBIGUOUS
   instead of blindly stripping colons into 4 digits.
5. OptimizedUserTurnStopStrategy dynamic timeouts:
   - 2.2s for partial digits (<10) preventing LLM interruptions after individual digits.
   - 0.15s immediate finalization once 10 valid digits or explicit final phrase is reached.
   - 0.45s conversational fallback.
6. Controlled test cases A through H:
   - Test A: "9215024687"
   - Test B: "9 2 1 5 0 2 4 6 8 7"
   - Test C: "nine two one five zero two four six eight seven"
   - Test D: "नौ दो एक पाँच शून्य दो चार छह आठ सात"
   - Test E: "nine two ek five zero do four six eight seven"
   - Test F: "921 502 4687"
   - Test G: "921" -> "502" -> "4687"
   - Test H: "921 05:02 4 04:01"
7. Multipliers: "double four", "double zero", "triple five".
8. Explicit final phrase detection: "that's my number", "यही मेरा नंबर है".
9. Deterministic privacy: Phone numbers are redacted in diagnostic logs (<REDACTED_NUMERIC>).
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.phone_digit_normalizer import (
    PhoneDigitNormalizer,
    PhoneCaptureBuffer,
    PhoneValidator,
    PhoneCaptureStatus,
    TokenType,
    mask_phone_number,
    is_valid_indian_mobile,
    log_deepgram_diagnostic_event,
)
from app.adapters.pipecat.turn_guard import OptimizedUserTurnStopStrategy
from pipecat.frames.frames import (
    TranscriptionFrame,
    InterimTranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)


class TestProductionFailureRegression:
    """Explicitly reproduces and validates the exact production failure."""

    def test_production_transcript_time_like_token_handling(self):
        """
        Production error: Deepgram with smart_format=True produced:
        'राहुल and मेरा phone number है 921 05:02 4 04:01.'

        The old system blindly stripped colons: 921 + 0502 + 4 + 0401 = 921050240401 (12 digits!).
        Then rejected it as '>10 digits'.
        The new system must identify '05:02' and '04:01' as TIME_LIKE_AMBIGUOUS,
        extract the unpadded digits ('9215024401'), and validate successfully.
        """
        raw_transcript = "राहुल and मेरा phone number है 921 05:02 4 04:01."
        tokens = PhoneDigitNormalizer.extract_tokens(raw_transcript)

        # Confirm time-like tokens were identified
        ambiguous = [t for t in tokens if t.token_type == TokenType.TIME_LIKE_AMBIGUOUS]
        assert len(ambiguous) == 2
        assert ambiguous[0].raw_text == "05:02"
        assert ambiguous[1].raw_text == "04:01"

        # Check candidate branches
        candidates = PhoneDigitNormalizer.extract_turn_candidates(raw_transcript)
        assert len(candidates) > 0

        # Feed to PhoneCaptureBuffer
        buf = PhoneCaptureBuffer(session_id="prod_reg_1")
        status = buf.process_utterance(raw_transcript)

        # Valid 10-digit number resolved without overflow
        assert len(buf.digits) == 10
        assert buf.digits == "9215024401"
        assert status == PhoneCaptureStatus.COMPLETE
        assert is_valid_indian_mobile(buf.digits)

    def test_sequential_individual_digits_accumulation(self):
        """
        Production error: Caller provided digits sequentially:
        921 -> 5 -> 0 -> 2 -> 4 04:01 -> 0 1
        Buffer must accumulate without resetting and reach 9215024401.
        """
        buf = PhoneCaptureBuffer(session_id="prod_reg_2")

        # Step 1: 921
        buf.process_utterance("921")
        assert buf.digits == "921"
        assert buf.status == PhoneCaptureStatus.PARTIAL

        # Step 2: 5
        buf.process_utterance("5")
        assert buf.digits == "9215"

        # Step 3: 0
        buf.process_utterance("0")
        assert buf.digits == "92150"

        # Step 4: 2
        buf.process_utterance("2")
        assert buf.digits == "921502"

        # Step 5: 4 04:01 (Deepgram time token artifact)
        buf.process_utterance("4 04:01")
        # 4 + 401 or 4 + 0401 -> should accumulate without exceeding 10 digits
        assert len(buf.digits) in (9, 10)

        # Step 6: 0 1
        buf.process_utterance("0 1")
        # Should now be valid 10 digits
        assert len(buf.digits) == 10
        assert is_valid_indian_mobile(buf.digits)
        assert buf.status == PhoneCaptureStatus.COMPLETE

    def test_interim_final_no_double_counting(self):
        """
        Deepgram interim revision:
        interim: "nine two"
        interim: "nine two one"
        final:   "nine two one"
        Must commit '921', NOT '92921' or '9221'.
        """
        buf = PhoneCaptureBuffer(session_id="interim_test")

        buf.process_utterance("nine two", is_interim=True)
        assert buf.digits == "92"

        buf.process_utterance("nine two one", is_interim=True)
        # Should replace / overlap, not blindly append
        assert buf.digits == "921"

        buf.process_utterance("nine two one", is_interim=False)
        assert buf.digits == "921"
        assert len(buf.digits) == 3


class TestControlledCasesAThroughH:
    """Evaluates controlled test cases A through H."""

    def test_case_a_continuous(self):
        """Test A: 9215024687"""
        buf = PhoneCaptureBuffer(session_id="case_a")
        status = buf.process_utterance("9215024687")
        assert buf.digits == "9215024687"
        assert status == PhoneCaptureStatus.COMPLETE

    def test_case_b_spaced_digits(self):
        """Test B: 9 2 1 5 0 2 4 6 8 7"""
        buf = PhoneCaptureBuffer(session_id="case_b")
        status = buf.process_utterance("9 2 1 5 0 2 4 6 8 7")
        assert buf.digits == "9215024687"
        assert status == PhoneCaptureStatus.COMPLETE

    def test_case_c_english_words(self):
        """Test C: nine two one five zero two four six eight seven"""
        buf = PhoneCaptureBuffer(session_id="case_c")
        status = buf.process_utterance("nine two one five zero two four six eight seven")
        assert buf.digits == "9215024687"
        assert status == PhoneCaptureStatus.COMPLETE

    def test_case_d_hindi_devanagari(self):
        """Test D: नौ दो एक पाँच शून्य दो चार छह आठ सात"""
        buf = PhoneCaptureBuffer(session_id="case_d")
        status = buf.process_utterance("नौ दो एक पाँच शून्य दो चार छह आठ सात")
        assert buf.digits == "9215024687"
        assert status == PhoneCaptureStatus.COMPLETE

    def test_case_e_hinglish_mixed(self):
        """Test E: nine two ek five zero do four six eight seven"""
        buf = PhoneCaptureBuffer(session_id="case_e")
        status = buf.process_utterance("nine two ek five zero do four six eight seven")
        assert buf.digits == "9215024687"
        assert status == PhoneCaptureStatus.COMPLETE

    def test_case_f_spaced_chunks(self):
        """Test F: 921 502 4687"""
        buf = PhoneCaptureBuffer(session_id="case_f")
        status = buf.process_utterance("921 502 4687")
        assert buf.digits == "9215024687"
        assert status == PhoneCaptureStatus.COMPLETE

    def test_case_g_multi_turn_pauses(self):
        """Test G: 921 -> pause -> 502 -> pause -> 4687"""
        buf = PhoneCaptureBuffer(session_id="case_g")
        buf.process_utterance("921")
        assert buf.digits == "921"
        buf.process_utterance("502")
        assert buf.digits == "921502"
        buf.process_utterance("4687")
        assert buf.digits == "9215024687"
        assert buf.status == PhoneCaptureStatus.COMPLETE

    def test_case_h_problematic_colons(self):
        """Test H: 921 05:02 4 04:01"""
        buf = PhoneCaptureBuffer(session_id="case_h")
        status = buf.process_utterance("921 05:02 4 04:01")
        assert buf.digits == "9215024401"
        assert status == PhoneCaptureStatus.COMPLETE


class TestSpeechPatternsAndMultipliers:
    """Tests speech patterns: double four, double zero, triple five."""

    def test_multipliers_english(self):
        cands = PhoneDigitNormalizer.extract_turn_candidates("double four and double zero and triple five")
        assert len(cands) > 0
        assert cands[0] == "4400555"

    def test_multipliers_hinglish(self):
        cands = PhoneDigitNormalizer.extract_turn_candidates("mera number hai nine eight double seven double six five five zero zero")
        assert cands[0] == "9877665500"
        assert is_valid_indian_mobile(cands[0])

    def test_explicit_final_phrases(self):
        assert PhoneDigitNormalizer.detect_final_phrase("That's my number")
        assert PhoneDigitNormalizer.detect_final_phrase("That is my final number")
        assert PhoneDigitNormalizer.detect_final_phrase("bas yahi mera number hai")
        assert PhoneDigitNormalizer.detect_final_phrase("यही मेरा नंबर है")
        assert not PhoneDigitNormalizer.detect_final_phrase("mera number kya hai")


class TestOptimizedUserTurnStopStrategyDynamicTimeouts:
    """Verifies that individual digits do NOT trigger immediate LLM turns."""

    @pytest.mark.asyncio
    async def test_partial_digits_extend_timeout_to_2_2s(self):
        """Partial digits must have timeout = 2.2s so caller can pause without LLM responding."""
        shared_state = {"in_phone_capture": True}
        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )
        strategy.trigger_user_turn_stopped = AsyncMock()

        # User speaks "921"
        await strategy.process_frame(TranscriptionFrame(text="921", user_id="user", timestamp="2026-10-04T00:00:00Z"))
        active_timeout = strategy._get_active_speech_timeout()
        assert active_timeout == 2.2

    @pytest.mark.asyncio
    async def test_complete_digits_reduce_timeout_to_0_15s(self):
        """10 valid digits must finalize immediately (0.15s)."""
        shared_state = {"in_phone_capture": True}
        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )
        strategy.trigger_user_turn_stopped = AsyncMock()

        # User speaks 10 digits
        await strategy.process_frame(TranscriptionFrame(text="9215024687", user_id="user", timestamp="2026-10-04T00:00:00Z"))
        active_timeout = strategy._get_active_speech_timeout()
        assert active_timeout == 0.15

    @pytest.mark.asyncio
    async def test_conversational_text_uses_default_0_45s(self):
        """Non-digit conversation must retain 0.45s timeout."""
        shared_state = {"in_phone_capture": False}
        strategy = OptimizedUserTurnStopStrategy(
            user_speech_timeout=0.45,
            digit_speech_timeout=2.2,
            digit_complete_timeout=0.15,
            shared_state=shared_state,
        )
        strategy.trigger_user_turn_stopped = AsyncMock()

        await strategy.process_frame(TranscriptionFrame(text="Hello how are you doing", user_id="user", timestamp="2026-10-04T00:00:00Z"))
        active_timeout = strategy._get_active_speech_timeout()
        assert active_timeout == 0.45


class TestDiagnosticLoggingObservability:
    """Verifies safe logging with redaction."""

    def test_diagnostic_log_redaction(self):
        record = log_deepgram_diagnostic_event(
            session_id="test_sess",
            turn_id=42,
            transcript="mera number 9215024687 hai",
            is_final=True,
            speech_final=True,
            confidence=0.98,
            buffer_before="921502",
            buffer_after="9215024687",
            validation_status="complete",
        )
        assert "9215024687" not in record["transcript"]
        assert "<REDACTED_NUMERIC>" in record["transcript"]
        assert "9215024687" not in record["buffer_after"]
        assert "******4687" in record["buffer_after"]
