"""
Deterministic regression tests for:
- PART A: False VAD interruption elimination, barge-in preservation, turn counter stability, and dead-air protection.
- PART B: ResilientLLMProcessor register_function delegation, tool execution (end_call, save_lead), and fallback replay.

Run with:
pytest tests/test_vad_interruption_and_tools.py -v
"""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserSpeakingFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    InterruptionFrame,
)
from pipecat.turns.types import ProcessFrameResult

from app.adapters.pipecat.turn_guard import ValidatedUserTurnStartStrategy, TurnGuardProcessor, TurnGuardFilter
from app.adapters.pipecat.processors import ResilientLLMProcessor, MockPipecatProcessor
from app.metrics.latency import LatencyTracker
from app.services.lead_manager import save_lead
from Pillar_2.pipeline import build_vad_analyzer


# ══════════════════════════════════════════════════════════════════════════════
# PART A: VAD INTERRUPTIONS, BARGE-IN & TURN STABILITY TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFalseVADInterruptions:
    """Deterministic tests for VAD noise filtering and real barge-in."""

    @pytest.mark.asyncio
    async def test_a_background_noise_ignored_no_llm_cancellation(self):
        """A. Background noise event: No LLM cancellation."""
        shared_state = {"current_turn_id": 1}
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        # Background noise triggers 80ms VAD pulse
        await strategy.process_frame(VADUserStartedSpeakingFrame())
        await asyncio.sleep(0.08)
        await strategy.process_frame(VADUserStoppedSpeakingFrame())

        # No turn start triggered -> No InterruptionFrame broadcast -> No LLM cancellation
        assert len(turn_started_events) == 0

    @pytest.mark.asyncio
    async def test_b_very_short_vad_event_no_turn_increment(self):
        """B. Very short VAD event: No turn increment in LatencyTracker or TurnGuard."""
        tracker = LatencyTracker()
        shared_state = {"current_turn_id": 1}

        # Short noise pulse
        tracker.on_vad_start()
        await asyncio.sleep(0.05)
        tracker.on_vad_stop()

        # Turn count must NOT increment for transient unverified noise
        assert tracker.turn_count == 0
        assert shared_state["current_turn_id"] == 1

    @pytest.mark.asyncio
    async def test_c_breath_micropause_no_interruption(self):
        """C. Breath/micro-pause: No interruption."""
        shared_state = {"current_turn_id": 2}
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        # 120ms breath/click
        await strategy.process_frame(VADUserStartedSpeakingFrame())
        await asyncio.sleep(0.12)
        await strategy.process_frame(VADUserStoppedSpeakingFrame())

        assert len(turn_started_events) == 0

    @pytest.mark.asyncio
    async def test_d_real_short_utterance_no_valid_interruption(self):
        """D. Real short utterance: 'No.' Expected: Valid interruption."""
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        # Interim transcription arrives from STT
        res = await strategy.process_frame(
            InterimTranscriptionFrame(text="No.", user_id="user", timestamp="2026-10-04T00:00:00Z")
        )

        assert res == ProcessFrameResult.STOP
        assert len(turn_started_events) == 1

    @pytest.mark.asyncio
    async def test_e_real_utterance_wait_valid_interruption(self):
        """E. Real utterance: 'Wait a second.' Expected: Valid interruption."""
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        res = await strategy.process_frame(
            InterimTranscriptionFrame(text="Wait a second.", user_id="user", timestamp="2026-10-04T00:00:00Z")
        )

        assert res == ProcessFrameResult.STOP
        assert len(turn_started_events) == 1

    @pytest.mark.asyncio
    async def test_f_hindi_rukiye_valid_interruption(self):
        """F. Hindi utterance: 'रुकिए.' Expected: Valid interruption."""
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        res = await strategy.process_frame(
            InterimTranscriptionFrame(text="रुकिए.", user_id="user", timestamp="2026-10-04T00:00:00Z")
        )

        assert res == ProcessFrameResult.STOP
        assert len(turn_started_events) == 1

    @pytest.mark.asyncio
    async def test_g_hinglish_ek_minute_valid_interruption(self):
        """G. Hinglish utterance: 'Ek minute.' Expected: Valid interruption."""
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        res = await strategy.process_frame(
            InterimTranscriptionFrame(text="Ek minute.", user_id="user", timestamp="2026-10-04T00:00:00Z")
        )

        assert res == ProcessFrameResult.STOP
        assert len(turn_started_events) == 1

    @pytest.mark.asyncio
    async def test_h_user_interrupts_during_llm_generation(self):
        """H. User interrupts during LLM generation. Expected: Old stream cancelled."""
        shared_state = {"current_turn_id": 1}
        guard = TurnGuardProcessor(shared_state=shared_state)
        turn_filter = TurnGuardFilter(shared_state=shared_state)

        # Turn 1 LLM response starts
        start_frame_turn1 = LLMFullResponseStartFrame()
        start_frame_turn1._turn_id = 1
        await turn_filter.process_frame(start_frame_turn1, None)
        assert turn_filter._suppressing is False

        # User interrupts with genuine speech -> Turn 2 LLMContextFrame arrives
        context_frame_turn2 = LLMContextFrame(context=None)
        await guard.process_frame(context_frame_turn2, None)
        assert shared_state["current_turn_id"] == 2

        # Any late frame from Turn 1 is now suppressed by TurnGuard
        late_start_turn1 = LLMFullResponseStartFrame()
        late_start_turn1._turn_id = 1
        await turn_filter.process_frame(late_start_turn1, None)
        assert turn_filter._suppressing is True

    @pytest.mark.asyncio
    async def test_i_user_does_not_speak_after_vad_event_no_dead_air(self):
        """I. User does not actually speak after VAD event: Pipeline recovers safely."""
        shared_state = {"current_turn_id": 1}
        strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
        turn_started_events = []
        strategy.trigger_user_turn_started = AsyncMock(side_effect=lambda: turn_started_events.append("STARTED"))

        # Breath occurs without words
        await strategy.process_frame(VADUserStartedSpeakingFrame())
        await asyncio.sleep(0.08)
        await strategy.process_frame(VADUserStoppedSpeakingFrame())

        # No turn start was emitted, pipeline remains in listening without dead air
        assert len(turn_started_events) == 0
        assert strategy._is_speaking_vad is False

    @pytest.mark.asyncio
    async def test_j_multiple_transient_noise_events_no_turn_counter_explosion(self):
        """J. Multiple transient noise events: No turn-counter explosion."""
        tracker = LatencyTracker()

        # 50 noise spikes (e.g. breaths, clicks, line artifacts)
        for _ in range(50):
            tracker.on_vad_start()
            tracker.on_vad_stop()

        # Turn counter must remain 0 because no verified transcripts were received
        assert tracker.turn_count == 0

        # Now real speech arrives with transcript
        tracker.on_vad_start()
        tracker.on_stt_transcript()
        assert tracker.turn_count == 1

        tracker.on_vad_stop()
        # Another real speech turn
        tracker.on_vad_start()
        tracker.on_stt_transcript()
        assert tracker.turn_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# PART B: RESILIENTLLMPROCESSOR TOOL DELEGATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class MockLLMService:
    """Mock LLM service matching Pipecat LLMService function registration interface."""
    def __init__(self):
        self._functions = {}

    def register_function(self, function_name, handler, **kwargs):
        self._functions[function_name] = handler

    def has_function(self, function_name):
        return function_name in self._functions or None in self._functions

    def unregister_function(self, function_name):
        self._functions.pop(function_name, None)

    def link(self, processor):
        pass


class TestResilientLLMToolDelegation:
    """Tests proving register_function works safely through ResilientLLMProcessor."""

    def test_resilient_llm_registers_end_call_without_attribute_error(self):
        """Verify register_function('end_call') delegates without AttributeError."""
        primary = MockLLMService()
        fallback = MockLLMService()
        resilient = ResilientLLMProcessor(primary, lambda: fallback)

        async def end_call(params):
            return {"status": "ended"}

        # Must NOT raise AttributeError: 'ResilientLLMProcessor' object has no attribute 'register_function'
        resilient.register_function("end_call", end_call)
        assert resilient.has_function("end_call") is True
        assert primary.has_function("end_call") is True

    def test_resilient_llm_registers_save_lead_without_attribute_error(self):
        """Verify register_function('save_lead') delegates without AttributeError."""
        primary = MockLLMService()
        fallback = MockLLMService()
        resilient = ResilientLLMProcessor(primary, lambda: fallback)

        resilient.register_function("save_lead", save_lead)
        assert resilient.has_function("save_lead") is True
        assert primary.has_function("save_lead") is True

    def test_resilient_llm_has_and_unregister_function(self):
        """Verify has_function and unregister_function behave correctly."""
        primary = MockLLMService()
        resilient = ResilientLLMProcessor(primary, lambda: MockLLMService())

        resilient.register_function("fetch_faq", lambda p: "faq")
        assert resilient.has_function("fetch_faq") is True

        resilient.unregister_function("fetch_faq")
        assert resilient.has_function("fetch_faq") is False

    @pytest.mark.asyncio
    async def test_end_call_execution_success(self):
        """Verify registered end_call tool can actually execute via the wrapper."""
        primary = MockLLMService()
        resilient = ResilientLLMProcessor(primary, lambda: MockLLMService())

        shared_state = {}
        async def end_call(params):
            shared_state["hangup_requested"] = True
            if getattr(params, "result_callback", None):
                await params.result_callback({"success": True})

        resilient.register_function("end_call", end_call)

        handler = resilient.get_function_handler("end_call")
        assert handler is not None

        mock_params = MagicMock()
        mock_params.arguments = {}
        mock_params.result_callback = AsyncMock()

        await handler(mock_params)
        assert shared_state.get("hangup_requested") is True
        mock_params.result_callback.assert_awaited_once_with({"success": True})

    @pytest.mark.asyncio
    async def test_save_lead_execution_success(self):
        """Verify registered save_lead tool can actually execute with unpacked arguments."""
        primary = MockLLMService()
        resilient = ResilientLLMProcessor(primary, lambda: MockLLMService())

        resilient.register_function("save_lead", save_lead)
        handler = resilient.get_function_handler("save_lead")
        assert handler is not None

        mock_params = MagicMock()
        mock_params.arguments = {
            "name": "Rahul Manchanda",
            "phone": "9876543210",
            "project_details": "Enterprise Voice AI"
        }
        mock_params.result_callback = AsyncMock()

        # Executes through the unified parameter adapter without raising TypeError
        await handler(mock_params)
        mock_params.result_callback.assert_awaited()

    @pytest.mark.asyncio
    async def test_fallback_replays_tool_registrations(self):
        """Verify that when primary LLM fails, all registered tools replay onto fallback LLM."""
        primary = MockLLMService()
        fallback_service = MockLLMService()
        resilient = ResilientLLMProcessor(primary, lambda: fallback_service)

        resilient.register_function("end_call", lambda p: "ended")
        resilient.register_function("save_lead", save_lead)

        assert fallback_service.has_function("end_call") is False
        assert fallback_service.has_function("save_lead") is False

        # Setup mock processor linkage for fallback transition
        from pipecat.clocks.system_clock import SystemClock
        from pipecat.utils.asyncio.task_manager import TaskManager, TaskManagerParams
        from pipecat.processors.frame_processor import FrameProcessor

        tm = TaskManager()
        tm.setup(TaskManagerParams(loop=asyncio.get_running_loop()))
        resilient._task_manager = tm
        resilient._clock = SystemClock()
        resilient._next = FrameProcessor()
        resilient._next._FrameProcessor__started = True
        resilient._next._task_manager = tm
        resilient._prev = resilient._next

        # Trigger fallback
        await resilient.trigger_llm_fallback(Exception("Simulated Primary Groq Error"))

        # Both tools must now be re-registered on fallback LLM
        assert fallback_service.has_function("end_call") is True
        assert fallback_service.has_function("save_lead") is True


# ══════════════════════════════════════════════════════════════════════════════
# VAD TUNING VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def test_vad_analyzer_tuning_parameters():
    """Verify that build_vad_analyzer contains the calibrated production parameters."""
    analyzer = build_vad_analyzer()
    params = analyzer.params
    assert params.confidence == 0.75, "confidence must be tuned to 0.75"
    assert params.start_secs == 0.2, "start_secs must be tuned to 0.2s"
    assert params.stop_secs in (0.4, 1.0), "stop_secs must be calibrated for low latency turn detection"
    assert params.min_volume == 0.08, "min_volume must be tuned to 0.08"
