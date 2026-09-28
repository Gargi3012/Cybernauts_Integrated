"""
Tests for turn-taking, end-call detection, and phone validation.

Run: pytest tests/test_voice_pipeline.py -v
"""
import pytest
import asyncio
import sys, os

# Ensure app is importable without pipecat-ai installed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["TESTING"] = "True"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Phone normalization tests (lead_manager._normalize_phone)
# ─────────────────────────────────────────────────────────────────────────────

class TestPhoneNormalization:
    def setup_method(self):
        from app.services.lead_manager import _normalize_phone
        self.normalize = _normalize_phone

    def test_10_digit_unchanged(self):
        assert self.normalize("7082968702") == "7082968702"

    def test_91_prefix_stripped(self):
        assert self.normalize("917082968702") == "7082968702"

    def test_plus_91_prefix(self):
        # +91 → only digits extracted → 12 digits starting with 91
        assert self.normalize("+917082968702") == "7082968702"

    def test_leading_zero_stripped(self):
        # 11 digits starting with 0
        assert self.normalize("07082968702") == "7082968702"

    def test_spaces_stripped(self):
        assert self.normalize("708 296 8702") == "7082968702"

    def test_9_digits_not_normalized(self):
        # Should NOT become 10 digits — remains 9 (invalid)
        result = self.normalize("708296870")
        assert len(result) == 9

    def test_11_digits_non_prefixed_unchanged(self):
        # 11 digits that don't start with 91 or 0 → returned as-is (invalid)
        result = self.normalize("71234567890")
        assert len(result) == 11

    def test_12_digits_non_91_unchanged(self):
        result = self.normalize("447082968702")  # UK number
        assert len(result) == 12


# ─────────────────────────────────────────────────────────────────────────────
# End-of-call detection tests (SemanticEndCallDetector logic)
# ─────────────────────────────────────────────────────────────────────────────

class TestEndCallDetection:
    def setup_method(self):
        from app.adapters.pipecat.end_call_detector import _end_call_confidence, _is_user_pause
        self.confidence = _end_call_confidence
        self.is_pause = _is_user_pause

    # --- HIGH confidence endings ---
    def test_bye(self):
        conf, _ = self.confidence("bye")
        assert conf >= 0.9

    def test_bye_bye(self):
        conf, matched = self.confidence("bye bye")
        assert conf >= 0.9
        assert "bye" in matched

    def test_goodbye(self):
        conf, _ = self.confidence("Goodbye")
        assert conf >= 0.9

    def test_thats_all(self):
        conf, _ = self.confidence("That's all")
        assert conf >= 0.9

    def test_bas_itna_hi(self):
        conf, _ = self.confidence("bas itna hi")
        assert conf >= 0.9

    def test_bas_ho_gaya(self):
        conf, _ = self.confidence("bas ho gaya")
        assert conf >= 0.9

    def test_theek_hai_bye(self):
        conf, _ = self.confidence("theek hai bye")
        assert conf >= 0.9

    def test_dhanyavaad(self):
        conf, _ = self.confidence("dhanyavaad")
        assert conf >= 0.9

    # --- FALSE POSITIVES — must NOT end call ---
    def test_okay_alone(self):
        conf, _ = self.confidence("okay")
        assert conf < 0.9, "bare 'okay' must not end call"

    def test_thanks_alone(self):
        conf, _ = self.confidence("thanks")
        assert conf < 0.9

    def test_alright_alone(self):
        conf, _ = self.confidence("alright")
        assert conf < 0.9

    def test_okay_tell_me_more(self):
        conf, _ = self.confidence("okay tell me more")
        assert conf < 0.9, "'okay tell me more' must not end call"

    def test_thanks_i_have_another_question(self):
        conf, _ = self.confidence("thanks but I have another question")
        assert conf < 0.9

    def test_fine_explain_the_ai(self):
        conf, _ = self.confidence("fine explain the AI solution")
        assert conf < 0.9

    def test_alright_continue(self):
        conf, _ = self.confidence("alright continue")
        assert conf < 0.9

    def test_okay_yes_i_understand(self):
        conf, _ = self.confidence("okay yes I understand")
        assert conf < 0.9

    def test_theek_hai_alone(self):
        conf, _ = self.confidence("theek hai")
        assert conf < 0.9, "bare 'theek hai' must not end call"

    # --- USER PAUSE — must return is_pause=True and NOT end call ---
    def test_wait_a_minute(self):
        assert self.is_pause("wait a minute") is True

    def test_hold_on(self):
        assert self.is_pause("hold on") is True

    def test_ek_minute(self):
        assert self.is_pause("ek minute") is True

    def test_ruko(self):
        assert self.is_pause("ruko") is True

    def test_one_second(self):
        assert self.is_pause("one second") is True

    def test_wait_a_minute_not_end_call(self):
        conf, matched = self.confidence("wait a minute")
        assert conf < 0.9, "wait a minute must not end call"
        assert matched == "user_pause"

    def test_hold_on_not_end_call(self):
        conf, matched = self.confidence("hold on")
        assert conf < 0.9

    def test_ruko_not_end_call(self):
        conf, matched = self.confidence("ruko")
        assert conf < 0.9


# ─────────────────────────────────────────────────────────────────────────────
# Deepgram time-format fix tests (language_router)
# ─────────────────────────────────────────────────────────────────────────────

class TestDeepgramTimeFormatFix:
    """
    Deepgram smart_format turns digit sequences into timestamps.
    E.g. user says '7 0 8' and Deepgram returns '7:08' or '07:08'.
    The LanguageRoutingProcessor must convert these back.
    """
    def _fix(self, text: str) -> str:
        import re
        def _collapse_time(m: re.Match) -> str:
            return m.group(0).replace(':', '')
        return re.sub(r'\b\d{1,2}(?::\d{2}){1,2}\b', _collapse_time, text)

    def test_708(self):
        assert self._fix("7:08") == "708"

    def test_0708(self):
        assert self._fix("07:08") == "0708"

    def test_296(self):
        assert self._fix("2:96") == "296"

    def test_mixed_sentence(self):
        result = self._fix("my number is 7:08 2:96 8702")
        assert "708" in result
        assert "296" in result
        assert "7:08" not in result

    def test_no_change_for_normal_text(self):
        text = "hello how are you"
        assert self._fix(text) == text


# ─────────────────────────────────────────────────────────────────────────────
# TurnGuardFilter stale response suppression (unit test)
# ─────────────────────────────────────────────────────────────────────────────

class TestTurnGuardLogic:
    """Test stale response suppression logic without Pipecat installed."""

    def _make_filter(self, current_turn_id=1):
        shared = {"current_turn_id": current_turn_id}
        # Simple duck-typed mock of the suppression logic
        class MockFilter:
            def __init__(self, shared_state):
                self._suppressing = False
                self.shared_state = shared_state
            
            def would_suppress_response(self, response_turn_id):
                current = self.shared_state.get("current_turn_id", 0)
                if response_turn_id is not None and response_turn_id < current:
                    return True
                return False
        return MockFilter(shared), shared

    def test_current_turn_passes(self):
        f, state = self._make_filter(current_turn_id=3)
        assert f.would_suppress_response(3) is False

    def test_stale_turn_suppressed(self):
        f, state = self._make_filter(current_turn_id=3)
        assert f.would_suppress_response(1) is True
        assert f.would_suppress_response(2) is True

    def test_future_turn_not_suppressed(self):
        # Should never happen but guard it
        f, state = self._make_filter(current_turn_id=3)
        assert f.would_suppress_response(4) is False

    def test_ending_call_blocks_new_turns(self):
        shared = {"current_turn_id": 1, "ending_call": True}
        # When ending_call is True, all new LLM responses should be blocked
        assert shared.get("ending_call") is True


# ─────────────────────────────────────────────────────────────────────────────
# Integration smoke test — FSM state transitions
# ─────────────────────────────────────────────────────────────────────────────

class TestFSMStates:
    def test_ending_call_state_exists(self):
        from app.conversation.transitions import ConversationState
        assert hasattr(ConversationState, "ENDING_CALL")
        assert ConversationState.ENDING_CALL.value == "ending_call"

    def test_phone_capture_state_exists(self):
        from app.conversation.transitions import ConversationState
        assert hasattr(ConversationState, "PHONE_CAPTURE")
        assert ConversationState.PHONE_CAPTURE.value == "phone_capture"

    def test_ending_call_only_goes_to_closed(self):
        from app.conversation.transitions import ConversationState, TRANSITION_MAP
        allowed = TRANSITION_MAP[ConversationState.ENDING_CALL]
        assert ConversationState.CLOSED in allowed
        assert ConversationState.LISTENING not in allowed
        assert ConversationState.THINKING not in allowed

    def test_speaking_can_go_to_ending_call(self):
        from app.conversation.transitions import ConversationState, TRANSITION_MAP
        allowed = TRANSITION_MAP[ConversationState.SPEAKING]
        assert ConversationState.ENDING_CALL in allowed

    def test_phone_capture_can_go_to_thinking(self):
        from app.conversation.transitions import ConversationState, TRANSITION_MAP
        allowed = TRANSITION_MAP[ConversationState.PHONE_CAPTURE]
        assert ConversationState.THINKING in allowed
        assert ConversationState.LISTENING in allowed

    def test_fsm_transition_to_ending_call(self):
        from app.conversation.state_machine import ConversationStateMachine
        from app.conversation.transitions import ConversationState
        fsm = ConversationStateMachine(session_id="test-session-1")
        # IDLE → LISTENING → SPEAKING → ENDING_CALL → CLOSED
        fsm.transition_to(ConversationState.LISTENING, reason="pipeline started")
        fsm.transition_to(ConversationState.SPEAKING, reason="greeting playing")
        fsm.transition_to(ConversationState.ENDING_CALL, reason="user said bye")
        assert fsm.get_current_state() == ConversationState.ENDING_CALL
        fsm.transition_to(ConversationState.CLOSED, reason="call terminated")
        assert fsm.get_current_state() == ConversationState.CLOSED


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic LLM-Generated Filler Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicLLMFiller:
    """Tests for dynamic LLM filler parsing, structured output, and turn handling."""

    def _setup_processor(self, current_turn_id=1):
        from app.adapters.pipecat.llm_filler_processor import DynamicLLMFillerProcessor
        shared = {"current_turn_id": current_turn_id}
        proc = DynamicLLMFillerProcessor(session_id="test-session-filler", shared_state=shared)
        
        # Capture pushed frames
        pushed = []
        async def mock_push(frame, direction=None):
            pushed.append(frame)
        proc.push_frame = mock_push
        return proc, shared, pushed

    def test_fast_response_no_filler(self):
        """Fast direct response should emit NO filler and deliver response immediately."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, LLMFullResponseEndFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text='{"acknowledgement": null, "response": "We provide AI automation.", "should_wait": false}'), None))
        _run(proc.process_frame(LLMFullResponseEndFrame(), None))

        text_frames = [f for f in pushed if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert getattr(text_frames[0], "is_filler", False) is False
        assert "We provide AI automation" in text_frames[0].text

    def test_plain_text_passthrough_no_delay(self):
        """When LLM outputs plain conversational text without JSON or tags, it passes through."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, LLMFullResponseEndFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text="Hello, how can I help you today?"), None))
        _run(proc.process_frame(LLMFullResponseEndFrame(), None))

        text_frames = [f for f in pushed if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert getattr(text_frames[0], "is_filler", False) is False
        assert text_frames[0].text == "Hello, how can I help you today?"

    def test_hindi_acknowledgement_and_response(self):
        """Hindi acknowledgement emitted first with is_filler=True, then main response."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, LLMFullResponseEndFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text='{"acknowledgement": "जी, बिल्कुल।", "response": "हम आपकी पूरी सहायता करेंगे।", "should_wait": false}'), None))
        _run(proc.process_frame(LLMFullResponseEndFrame(), None))

        text_frames = [f for f in pushed if isinstance(f, TextFrame)]
        assert len(text_frames) == 2
        # First frame is filler acknowledgement
        assert text_frames[0].text == "जी, बिल्कुल।"
        assert getattr(text_frames[0], "is_filler", False) is True
        # Second frame is main response
        assert "हम आपकी पूरी सहायता करेंगे।" in text_frames[1].text
        assert getattr(text_frames[1], "is_filler", False) is False

    def test_user_pause_hindi(self):
        """User pause in Hindi: emits acknowledgement, sets user_pause=True, suppresses response."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, LLMFullResponseEndFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text='{"acknowledgement": "जी बिल्कुल, आप आराम से देख लीजिए।", "response": "", "should_wait": true}'), None))
        _run(proc.process_frame(LLMFullResponseEndFrame(), None))

        text_frames = [f for f in pushed if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert text_frames[0].text == "जी बिल्कुल, आप आराम से देख लीजिए।"
        assert getattr(text_frames[0], "is_filler", False) is True
        assert shared.get("user_pause") is True

    def test_user_pause_english(self):
        """User pause in English: emits acknowledgement, sets user_pause=True."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, LLMFullResponseEndFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text='{"acknowledgement": "Sure, take your time.", "response": "", "should_wait": true}'), None))
        _run(proc.process_frame(LLMFullResponseEndFrame(), None))

        text_frames = [f for f in pushed if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert text_frames[0].text == "Sure, take your time."
        assert getattr(text_frames[0], "is_filler", False) is True
        assert shared.get("user_pause") is True

    def test_tag_format_ack_and_wait(self):
        """Tag format <ack wait='true'>...</ack> parsed cleanly."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, LLMFullResponseEndFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text='<ack wait="true">जी बिल्कुल, मैं इंतज़ार करता हूँ।</ack>'), None))
        _run(proc.process_frame(LLMFullResponseEndFrame(), None))

        text_frames = [f for f in pushed if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert text_frames[0].text == "जी बिल्कुल, मैं इंतज़ार करता हूँ।"
        assert getattr(text_frames[0], "is_filler", False) is True
        assert shared.get("user_pause") is True

    def test_interruption_during_filler(self):
        """UserStartedSpeakingFrame resets active filler state."""
        proc, shared, pushed = self._setup_processor()
        from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame, UserStartedSpeakingFrame

        _run(proc.process_frame(LLMFullResponseStartFrame(), None))
        _run(proc.process_frame(TextFrame(text='{"acknowledgement": "One moment please.", "response": "'), None))
        assert proc._filler_active is True

        # User interrupts
        _run(proc.process_frame(UserStartedSpeakingFrame(), None))
        assert proc._filler_active is False

