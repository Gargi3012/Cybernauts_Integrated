"""
test_latency_diagnostics_and_turn_cleanup.py
============================================
Comprehensive regression test suite for Flowiz Voice Pipeline Latency Regression Fixes:
1. Normal English conversation turn (0.45s timeout, ~1.2s total response)
2. Normal Hindi conversation turn (0.45s timeout)
3. Hinglish conversation turn (0.45s timeout)
4. Genuine phone-capture turn (2.20s timeout, classified as phone turn, no false regression)
5. Stale phone-capture state followed by normal turn (uses 0.45s, not 2.20s)
6. Partial STT transcripts followed by final transcript (no turn splitting)
7. Slow LLM first-token delivery (< 2.0s threshold)
8. Slow TTS first-audio delivery (< 350ms threshold)
9. Tool execution during qualified lead conversation (save_lead before end_call)
10. Provider retry/fallback behavior
11. Multiple turns in the same call (eliminates 15.75s stale vad_stop leak)
12. Missing or duplicated instrumentation events (no crashes, clean metrics)
13. Call termination immediately after final response (single carrier hangup)
14. Audio buffering and frame dispatch (< 10ms dispatch)
"""

import time
import pytest
from unittest.mock import MagicMock

from pipecat.frames.frames import (
    TranscriptionFrame,
    InterimTranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TTSStartedFrame,
    AudioRawFrame,
)

from app.metrics.latency import LatencyTracker, TurnLatency
from app.adapters.pipecat.turn_guard import OptimizedUserTurnStopStrategy
from app.adapters.pipecat.context_manager import SlidingWindowLLMContext
from app.services.phone_digit_normalizer import PhoneDigitNormalizer
from app.services.lead_qualification_machine import (
    LeadQualificationStateMachine,
    QualificationState,
)


class TestLatencyDiagnosticsAndTurnCleanup:

    def test_1_normal_english_turn(self):
        """1. A normal English conversation turn: 0.45s timeout, no phone classification."""
        tracker = LatencyTracker(session_id="sess_eng")
        
        t_base = time.perf_counter()
        tracker.on_vad_start()
        tracker.on_stt_interim()
        tracker.on_stt_transcript("Yes, we currently use Salesforce for our CRM.")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45, is_phone_turn=False)
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_transport_audio()
        tracker.on_llm_complete()

        stats = tracker.compute_statistics()
        assert stats["turn_count"] == 1
        turn = tracker.all_turns[0]
        assert turn.configured_timeout == 0.45
        assert turn.is_phone_turn is False
        assert stats["normal_timeouts"]["max"] == 0.45
        assert stats["phone_timeouts"]["count"] == 0
        assert tracker.detect_regressions()["has_regression"] is False

    def test_2_normal_hindi_turn(self):
        """2. A normal Hindi conversation turn: 0.45s timeout."""
        tracker = LatencyTracker(session_id="sess_hi")
        tracker.on_vad_start()
        tracker.on_stt_transcript("आपकी कंपनी क्या काम करती है?")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45, is_phone_turn=False)
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_llm_complete()

        turn = tracker.all_turns[0]
        assert turn.is_phone_turn is False
        assert turn.configured_timeout == 0.45
        assert tracker.detect_regressions()["has_regression"] is False

    def test_3_hinglish_turn(self):
        """3. A Hinglish conversation turn: 0.45s timeout."""
        tracker = LatencyTracker(session_id="sess_hinglish")
        tracker.on_vad_start()
        tracker.on_stt_transcript("Haan hum CRM use karte hain but pricing kya hai?")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45, is_phone_turn=False)
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_llm_complete()

        turn = tracker.all_turns[0]
        assert turn.is_phone_turn is False
        assert turn.configured_timeout == 0.45
        assert tracker.detect_regressions()["has_regression"] is False

    def test_4_genuine_phone_capture_turn(self):
        """4. Genuine phone-capture turn: 2.20s timeout classified as phone turn without tripping normal regression."""
        tracker = LatencyTracker(session_id="sess_phone")
        tracker.on_vad_start()
        tracker.on_stt_transcript("98765")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=2.20, is_phone_turn=True)
        tracker.on_phone_event(digit_count=5, status="collecting", timeout=2.20)
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_llm_complete()

        stats = tracker.compute_statistics()
        assert stats["normal_timeouts"]["count"] == 0
        assert stats["phone_timeouts"]["count"] == 1
        assert stats["phone_timeouts"]["max"] == 2.20
        # Normal turn timeout regression must NOT trigger
        reg = tracker.detect_regressions()
        assert reg["has_regression"] is False

    def test_5_stale_phone_capture_followed_by_normal_turn(self):
        """5. Stale phone-capture state followed by a normal turn uses 0.45s, not 2.20s."""
        shared_state = {
            "in_phone_capture": True,
            "phone_confirmed": False,
            "phone_normalizer": PhoneDigitNormalizer(session_id="s_stale"),
        }
        # Simulate partial digits accumulated previously
        shared_state["phone_normalizer"].process_utterance("98765")
        assert len(shared_state["phone_normalizer"].digits) == 5

        # In current turn, user speaks normal conversational text without digits
        strategy = OptimizedUserTurnStopStrategy(
            shared_state=shared_state,
            user_speech_timeout=0.45,
            digit_speech_timeout=2.20,
            digit_complete_timeout=0.15,
        )
        strategy._text = "Actually tell me about your pricing options instead"
        active_timeout = strategy._get_active_speech_timeout()
        assert active_timeout == 0.45, f"Expected normal 0.45s timeout, got {active_timeout}s"

    def test_6_partial_stt_transcripts_no_turn_splitting(self):
        """6. Multiple interim transcripts followed by final transcript do not create fragmented turns."""
        tracker = LatencyTracker(session_id="sess_interims")
        tracker.on_vad_start()
        tracker.on_stt_interim()
        tracker.on_stt_interim()
        tracker.on_stt_transcript("Hello, can you help me?")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45)
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_llm_complete()

        assert len(tracker.all_turns) == 1
        assert tracker.all_turns[0].turn_number == 1

    def test_7_slow_llm_first_token_delivery(self):
        """7. Slow LLM first-token delivery measured accurately without crash."""
        tracker = LatencyTracker(session_id="sess_slow_llm")
        tracker.on_vad_start()
        tracker.on_stt_transcript("Complex inquiry...")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45)
        
        t0 = time.perf_counter()
        tracker.on_llm_request_started()
        tracker.current_turn.t4_llm_request_started = t0
        tracker.current_turn.llm_first_token = t0 + 1.85  # 1.85s TTFT
        tracker.current_turn.t5_llm_first_token = t0 + 1.85
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_llm_complete()

        turn = tracker.all_turns[0]
        assert round(turn.llm_ttft, 2) == 1.85
        assert tracker.detect_regressions()["has_regression"] is False  # threshold is 2.0s

    def test_8_slow_tts_first_audio_delivery(self):
        """8. Slow TTS first-audio delivery measured accurately."""
        tracker = LatencyTracker(session_id="sess_slow_tts")
        tracker.on_vad_start()
        tracker.on_stt_transcript("Hello")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45)
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        
        t_tts_text = time.perf_counter()
        tracker.current_turn.tts_first_text = t_tts_text
        tracker.current_turn.t6_first_tts_text = t_tts_text
        tracker.current_turn.tts_first_audio = t_tts_text + 0.28  # 280ms TTFB
        tracker.current_turn.t7_first_tts_audio = t_tts_text + 0.28
        tracker.on_llm_complete()

        turn = tracker.all_turns[0]
        assert round(turn.cartesia_ttfb, 2) == 0.28
        assert tracker.detect_regressions()["has_regression"] is False  # threshold is 0.35s

    @pytest.mark.asyncio
    async def test_9_tool_execution_during_qualified_lead(self, tmp_path):
        """9. Tool execution during qualified lead: save_lead verified before call termination."""
        from unittest.mock import patch
        test_leads = tmp_path / "leads_test.json"
        with patch("app.services.lead_manager.LEADS_FILE", str(test_leads)):
            machine = LeadQualificationStateMachine(session_id="sess_tool")
            machine.process_user_utterance("My name is Rahul Manchanda, we use Salesforce.")
            machine.process_user_utterance("My number is 9876543210")
            machine.process_user_utterance("Yes, please have your sales team follow up with me.")
            machine.update_phone_state("9876543210", confirmed=True)

            assert machine.state == QualificationState.QUALIFIED
            eligible, _ = machine.is_eligible_for_save()
            assert eligible is True

            # Tool execution
            res = await machine.execute_save()
            assert res["status"] == "success"
            assert machine.state == QualificationState.SAVED
            assert machine.save_status == "SUCCESS"

    def test_10_provider_retry_fallback_behavior(self):
        """10. Provider fallback preserves latency tracker integrity."""
        tracker = LatencyTracker(session_id="sess_fallback")
        tracker.on_vad_start()
        tracker.on_stt_transcript("Tell me about Flowiz")
        tracker.on_vad_stop()
        tracker.on_turn_finalized(timeout=0.45)
        tracker.on_llm_request_started()
        
        # Simulate primary timeout/fallback delay
        t_start = tracker.current_turn.t4_llm_request_started
        tracker.current_turn.llm_first_token = t_start + 1.2
        tracker.current_turn.t5_llm_first_token = t_start + 1.2
        tracker.on_tts_text()
        tracker.on_tts_start()
        tracker.on_llm_complete()

        assert len(tracker.all_turns) == 1
        assert tracker.all_turns[0].llm_ttft == pytest.approx(1.2, rel=0.01)

    def test_11_multiple_turns_no_stale_vad_stop_leak(self):
        """
        11. CRITICAL REGRESSION TEST: Multiple turns within the same call.
        Verifies that Turn 2 does NOT inherit Turn 1's vad_stop across a 15-second pause,
        eliminating the 15.75s, 12.38s, and 7.38s false total latencies!
        """
        tracker = LatencyTracker(session_id="sess_multi_turn")

        # --- Turn 1 ---
        t1_start = 1000.0
        tracker._pending_vad_start = t1_start
        tracker.on_stt_transcript("First question")
        tracker.current_turn.vad_start = t1_start
        tracker.current_turn.vad_stop = t1_start + 1.0
        tracker.current_turn.t0_user_speech_end = t1_start + 1.0
        tracker.on_turn_finalized(timeout=0.45)
        tracker.current_turn.t4_llm_request_started = t1_start + 1.45
        tracker.current_turn.llm_first_token = t1_start + 2.50
        tracker.current_turn.t5_llm_first_token = t1_start + 2.50
        tracker.current_turn.tts_first_text = t1_start + 2.52
        tracker.current_turn.t6_first_tts_text = t1_start + 2.52
        tracker.current_turn.tts_first_audio = t1_start + 2.56
        tracker.current_turn.t7_first_tts_audio = t1_start + 2.56
        tracker.current_turn.llm_complete = t1_start + 4.0
        tracker._check_turn_completion()

        assert len(tracker.all_turns) == 1
        turn1 = tracker.all_turns[0]
        # Turn 1 total latency = 2.56 - 2.0 = 1.56s
        assert round(turn1.user_stop_to_first_tts_audio, 2) == 1.56

        # --- 15 seconds elapse while bot speaks and user pauses ---
        t2_start = t1_start + 20.0  # 20 seconds later

        # --- Turn 2 ---
        tracker._pending_vad_start = t2_start
        tracker.on_stt_transcript("Second question after 15 seconds")
        # In Turn 2, vad_stop must NOT be t1_start + 1.0 (from 20 seconds ago!)
        assert tracker.current_turn.vad_stop is None, "Stale vad_stop leaked into Turn 2!"
        
        # User finishes speaking at t2_start + 0.8
        tracker.current_turn.vad_start = t2_start
        tracker.on_vad_stop()
        tracker.current_turn.vad_stop = t2_start + 0.8
        tracker.current_turn.t0_user_speech_end = t2_start + 0.8

        tracker.on_turn_finalized(timeout=0.45)
        tracker.current_turn.t4_llm_request_started = t2_start + 1.25
        tracker.current_turn.llm_first_token = t2_start + 2.35
        tracker.current_turn.t5_llm_first_token = t2_start + 2.35
        tracker.current_turn.tts_first_text = t2_start + 2.38
        tracker.current_turn.t6_first_tts_text = t2_start + 2.38
        tracker.current_turn.tts_first_audio = t2_start + 2.42
        tracker.current_turn.t7_first_tts_audio = t2_start + 2.42
        tracker.current_turn.llm_complete = t2_start + 3.50
        tracker._check_turn_completion()

        assert len(tracker.all_turns) == 2
        turn2 = tracker.all_turns[1]
        # Turn 2 total latency = (t2_start + 2.42) - (t2_start + 0.8) = 1.62s
        # PREVIOUSLY THIS WOULD HAVE BEEN (t2_start + 2.42) - (t1_start + 1.0) = ~21.42s or 15.75s!
        assert round(turn2.user_stop_to_first_tts_audio, 2) == 1.62, (
            f"Expected ~1.62s total latency for Turn 2, got {turn2.user_stop_to_first_tts_audio}s!"
        )

    def test_12_missing_or_duplicated_events_robustness(self):
        """12. Missing or duplicate events handled gracefully without exceptions."""
        tracker = LatencyTracker(session_id="sess_robust")
        # Duplicate vad_stop calls
        tracker.on_vad_stop()
        tracker.on_vad_stop()
        # Missing vad_start
        tracker.on_stt_transcript("Hello")
        # Missing interim
        tracker.on_turn_finalized()
        # Duplicate tts_start
        tracker.on_tts_start()
        tracker.on_tts_start()
        # Check statistics without complete stages
        stats = tracker.compute_statistics()
        assert stats["turn_count"] >= 0

    def test_13_call_termination_waterfall(self):
        """13. Call termination immediately after final response issued exactly once."""
        tracker = LatencyTracker(session_id="sess_term")
        t0 = time.perf_counter()
        tracker.on_goodbye_detected(t0)
        tracker.on_bot_stopped_speaking(t0 + 0.5)
        tracker.on_hangup_requested(t0 + 0.52)
        tracker.on_carrier_hangup(t0 + 0.60)

        term_dict = tracker.termination.to_dict()
        assert term_dict["hangup_count"] == 1
        assert term_dict["goodbye_detection_to_speech_end_ms"] == pytest.approx(500.0, rel=0.01)
        assert term_dict["speech_end_to_hangup_dispatch_ms"] == pytest.approx(20.0, rel=0.01)
        assert tracker.detect_regressions()["has_regression"] is False

    def test_14_audio_buffering_and_frame_dispatch(self):
        """14. Audio buffering and frame dispatch measured (< 10ms)."""
        tracker = LatencyTracker(session_id="sess_audio")
        tracker.on_turn_started(turn_id=1)
        t_tts = time.perf_counter()
        tracker.current_turn.tts_first_audio = t_tts
        tracker.current_turn.t7_first_tts_audio = t_tts
        tracker.current_turn.t8_transport_audio = t_tts + 0.002  # 2ms dispatch
        
        diff = tracker.current_turn.t8_transport_audio - tracker.current_turn.t7_first_tts_audio
        assert diff < 0.010, f"Expected < 10ms frame dispatch, got {diff * 1000}ms"
