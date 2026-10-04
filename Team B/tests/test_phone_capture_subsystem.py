"""
test_phone_capture_subsystem.py — Deterministic Test Suite for Phone Capture Subsystem
=====================================================================================
Covers complete Test Matrix (A through T) specified in Step 18 of the specification:
A. Individual digits
B. Grouped digits
C. Mixed spacing
D. Colon/timestamp STT
E. Observed bug: '921 05:02 4 04:01'
F. Multiple turns: '921' -> '5' -> '0' -> '2' -> '4' -> '04:01'
G. Hindi Devanagari words
H. Hinglish / Romanized words
I. Noise words filtering ('9 2 sun lo')
J. Partial number buffer
K. Repeated STT (interim -> final)
L. Duplicate turn handling
M. Spoken correction ('last digit 8 nahi 9')
N. Overflow handling
O. Valid 10-digit completion
P. Invalid Indian phone number (starts with 1-5)
Q. User pause between utterances
R. Hindi/Hinglish mixed speech
S. Very short single-digit utterances
T. Long single-turn utterance

Additional validations:
- Multiplier handling ('double nine', 'triple zero')
- Security & masking verification (raw digits never exposed in log helpers)
- CriticalCallMemory and SlidingWindowLLMContext integration
- ConversationState.PHONE_CAPTURE FSM transitions
"""

import pytest
from app.services.phone_digit_normalizer import (
    PhoneDigitNormalizer,
    PhoneCaptureStatus,
    mask_phone_number,
    is_valid_indian_mobile,
)
from app.adapters.pipecat.context_manager import (
    CriticalCallMemory,
    SlidingWindowLLMContext,
    extract_phone_digits_from_text,
)
from app.conversation.transitions import ConversationState, TRANSITION_MAP


class TestPhoneDigitNormalizerMatrix:
    """Deterministic validation of Test Matrix items A through T."""

    def test_matrix_a_individual_digits(self):
        norm = PhoneDigitNormalizer(session_id="test_a")
        norm.process_utterance("9 8 7 6 5 4 3 2 1 0")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_b_grouped_digits(self):
        norm = PhoneDigitNormalizer(session_id="test_b")
        norm.process_utterance("9876 543210")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_c_mixed_spacing(self):
        norm = PhoneDigitNormalizer(session_id="test_c")
        norm.process_utterance("98 76 54 32 10")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_d_colon_timestamp_stt(self):
        norm = PhoneDigitNormalizer(session_id="test_d")
        norm.process_utterance("98 76 54:32 10")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_e_observed_bug_single_turn(self):
        """Observed Deepgram transcript: '921 05:02 4 04:01'."""
        norm = PhoneDigitNormalizer(session_id="test_e")
        norm.process_utterance("921 05:02 4 04:01")
        assert norm.digits == "9215024401"
        assert norm.status == PhoneCaptureStatus.COMPLETE
        assert is_valid_indian_mobile(norm.digits)

    def test_matrix_f_multi_turn_accumulation(self):
        """Observed multi-turn sequence: '921', '5', '0', '2', '4', '04:01'."""
        norm = PhoneDigitNormalizer(session_id="test_f")
        turns = ["921", "5", "0", "2", "4", "04:01"]
        expected_counts = [3, 4, 5, 6, 7, 10]
        
        for turn, expected_len in zip(turns, expected_counts):
            norm.process_utterance(turn)
            assert len(norm.digits) == expected_len

        assert norm.digits == "9215024401"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_g_hindi_devanagari(self):
        norm = PhoneDigitNormalizer(session_id="test_g")
        norm.process_utterance("नौ आठ सात छह पाँच चार तीन दो एक शून्य")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_h_hinglish(self):
        norm = PhoneDigitNormalizer(session_id="test_h")
        norm.process_utterance("nau aath saat chhah paanch chaar teen do ek zero")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_i_noise_words(self):
        norm = PhoneDigitNormalizer(session_id="test_i")
        norm.process_utterance("9 2 sun lo")
        assert norm.digits == "92"
        assert norm.status == PhoneCaptureStatus.PARTIAL

    def test_matrix_j_partial_number(self):
        norm = PhoneDigitNormalizer(session_id="test_j")
        norm.process_utterance("9 2")
        assert norm.digits == "92"
        assert norm.status == PhoneCaptureStatus.PARTIAL
        state_dict = norm.to_dict()
        assert state_dict["digits_collected"] == 2
        assert state_dict["digits_remaining"] == 8

    def test_matrix_k_repeated_stt_interim_final(self):
        norm = PhoneDigitNormalizer(session_id="test_k")
        # Interim then final with same content
        norm.process_utterance("987", is_interim=True)
        assert norm.digits == "987"
        norm.process_utterance("987", is_interim=False)
        assert norm.digits == "987"

    def test_matrix_l_duplicate_turn(self):
        norm = PhoneDigitNormalizer(session_id="test_l")
        norm.process_utterance("98765")
        assert norm.digits == "98765"
        # Duplicate final transcript submitted again immediately
        norm.process_utterance("98765")
        assert norm.digits == "98765"
        assert norm.last_action == "duplicate_ignored"

    def test_matrix_m_spoken_correction(self):
        norm = PhoneDigitNormalizer(session_id="test_m")
        norm.process_utterance("9876543218")
        assert norm.digits == "9876543218"
        norm.process_utterance("last digit 8 nahi 9")
        assert norm.digits == "9876543219"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_n_overflow_handling(self):
        norm = PhoneDigitNormalizer(session_id="test_n")
        norm.process_utterance("98765432101")
        assert len(norm.digits) == 11
        assert norm.status == PhoneCaptureStatus.OVERFLOW
        # Buffer is NOT wiped; remains intact for targeted recovery
        assert "98765432101" in norm.digits

    def test_matrix_o_valid_10_digit_completion(self):
        norm = PhoneDigitNormalizer(session_id="test_o")
        norm.process_utterance("7890123456")
        assert norm.status == PhoneCaptureStatus.COMPLETE
        assert is_valid_indian_mobile(norm.digits) is True

    def test_matrix_p_invalid_number_prefix(self):
        norm = PhoneDigitNormalizer(session_id="test_p")
        # 10 digits starting with 1 (not valid Indian mobile 6,7,8,9)
        norm.process_utterance("1234567890")
        assert norm.status == PhoneCaptureStatus.INVALID
        assert is_valid_indian_mobile(norm.digits) is False

    def test_matrix_q_user_pause(self):
        norm = PhoneDigitNormalizer(session_id="test_q")
        norm.process_utterance("987")
        assert norm.digits == "987"
        # Silence / pause produces empty transcript
        norm.process_utterance("")
        assert norm.digits == "987"
        norm.process_utterance("6543210")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_r_mixed_hindi_hinglish_speech(self):
        norm = PhoneDigitNormalizer(session_id="test_r")
        norm.process_utterance("mera number hai 9 8 saat chhe five four three 2 1 zero")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_matrix_s_very_short_utterances(self):
        norm = PhoneDigitNormalizer(session_id="test_s")
        for d in ["9", "8", "7"]:
            norm.process_utterance(d)
        assert norm.digits == "987"
        assert norm.status == PhoneCaptureStatus.PARTIAL

    def test_matrix_t_long_utterance(self):
        norm = PhoneDigitNormalizer(session_id="test_t")
        norm.process_utterance("Haan bilkul please note kar lijiye 9876543210 hai mera mobile number")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE


class TestPhoneCaptureAdvancedFeatures:
    """Tests multipliers, security masking, FSM, and memory integration."""

    def test_multipliers(self):
        norm = PhoneDigitNormalizer(session_id="test_mult")
        norm.process_utterance("double nine eight seven triple zero one two three")
        assert norm.digits == "9987000123"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_devanagari_numerals(self):
        norm = PhoneDigitNormalizer(session_id="test_dev_num")
        norm.process_utterance("९८७६५४३२१०")
        assert norm.digits == "9876543210"
        assert norm.status == PhoneCaptureStatus.COMPLETE

    def test_security_masking(self):
        digits = "9876543210"
        masked = mask_phone_number(digits)
        assert masked == "******3210"
        assert "987654" not in masked

        short = "98"
        assert mask_phone_number(short) == "*** (len=2)"

    def test_critical_memory_integration(self):
        mem = CriticalCallMemory(session_id="sess_crit_mem")
        # Multi-turn through CriticalCallMemory
        mem.extract_from_user_utterance("My phone is 921 05:02")
        assert len(mem.phone_digits) > 0
        mem.extract_from_user_utterance("4 04:01")
        assert mem.phone_digits == "9215024401"

        rendered = mem.render_memory_block()
        assert "<critical_conversation_memory>" in rendered
        assert "<phone_capture_state>" in rendered
        assert "Status: complete" in rendered

    def test_sliding_window_llm_context_integration(self):
        ctx = SlidingWindowLLMContext(
            session_id="sess_window_phone",
            max_window_messages=4,
            messages=[{"role": "system", "content": "Assistant prompt"}]
        )
        ctx.add_message({"role": "user", "content": "My number is 9876 543210"})
        ctx.add_message({"role": "assistant", "content": "Noted."})

        messages = ctx.get_messages()
        sys_msg = messages[0]["content"]
        assert "<phone_capture_state>" in sys_msg
        assert "Status: complete" in sys_msg

    def test_fsm_phone_capture_transitions(self):
        # Validate PHONE_CAPTURE state in transition map
        allowed_from_listening = TRANSITION_MAP[ConversationState.LISTENING]
        assert ConversationState.PHONE_CAPTURE in allowed_from_listening

        allowed_from_transcribing = TRANSITION_MAP[ConversationState.TRANSCRIBING]
        assert ConversationState.PHONE_CAPTURE in allowed_from_transcribing

        allowed_from_phone_capture = TRANSITION_MAP[ConversationState.PHONE_CAPTURE]
        assert ConversationState.THINKING in allowed_from_phone_capture
        assert ConversationState.LISTENING in allowed_from_phone_capture
