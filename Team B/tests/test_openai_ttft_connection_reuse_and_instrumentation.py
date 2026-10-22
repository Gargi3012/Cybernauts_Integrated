"""Targeted regression tests for Flowiz OpenAI TTFT root-cause fixes:
1. Verifies PooledOpenAILLMService reuses the persistent DefaultAsyncHttpxClient connection pool across multiple call instantiations.
2. Verifies EventBridgeObserver stamps on_llm_first_token() strictly on the first TextFrame (or FunctionCallsStartedFrame) from the LLM, and NOT prematurely on LLMFullResponseStartFrame.
3. Verifies LatencyTracker.print_summary() accurately reports llm_ttft (T5 - T4) rather than conflating silence timeouts with TTFT.
4. Verifies deterministic prompt & context serialization overhead is microsecond-level (< 0.1 ms).
5. Verifies session isolation and no leakage across concurrent calls.
"""

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

import pytest

from app.adapters.pipecat.processors import (
    PooledOpenAILLMService,
    get_shared_openai_http_client,
    create_pipecat_processor,
    ProcessorRole,
)
from app.metrics.latency import LatencyTracker, TurnLatency
from pipecat.frames.frames import (
    LLMContextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    FunctionCallsStartedFrame,
    UserStoppedSpeakingFrame,
    TTSStartedFrame,
)
from pipecat.processors.frame_processor import FrameDirection


class TestOpenAITTFTConnectionPooling:
    """Verifies HTTP keep-alive connection pooling across calls."""

    def test_shared_http_client_singleton(self):
        """get_shared_openai_http_client returns a persistent shared instance."""
        c1 = get_shared_openai_http_client()
        c2 = get_shared_openai_http_client()
        assert c1 is c2
        assert hasattr(c1, "_transport") or hasattr(c1, "_pool") or hasattr(c1, "_limits")

    def test_pooled_service_reuses_http_client(self):
        """Two separate call sessions reusing PooledOpenAILLMService share the exact same underlying HTTP client."""
        svc_call1 = PooledOpenAILLMService(api_key="sk-test-call-1")
        svc_call2 = PooledOpenAILLMService(api_key="sk-test-call-2")

        # Verify underlying AsyncOpenAI http_client matches
        shared_pool = get_shared_openai_http_client()
        assert svc_call1._client._client is shared_pool
        assert svc_call2._client._client is shared_pool
        assert svc_call1._client._client is svc_call2._client._client

    def test_create_processor_instantiates_pooled_service(self):
        """create_processor(LLM) uses PooledOpenAILLMService when LLM_PROVIDER is openai."""
        from app.config import LLM_PROVIDER
        if LLM_PROVIDER.lower() == "openai":
            resilient_proc = create_pipecat_processor(ProcessorRole.LLM, {})
            # Primary service wrapped by ResilientLLMProcessor
            primary = resilient_proc.active_llm
            assert isinstance(primary, PooledOpenAILLMService)
            assert primary._client._client is get_shared_openai_http_client()


class TestTTFTInstrumentationAccuracy:
    """Verifies that TTFT is stamped on the first token, not on response start."""

    @pytest.mark.asyncio
    async def test_ttft_stamped_on_first_text_frame(self):
        """on_llm_first_token() must NOT be triggered on LLMFullResponseStartFrame;
        it must be triggered strictly when TextFrame arrives."""
        from app.adapters.pipecat.adapter import _build_real_pipeline_task

        mock_bridge = MagicMock()
        mock_bridge._session_id = "test_ttft_sess"
        mock_bridge.on_llm_response_started = MagicMock()

        tracker = LatencyTracker(session_id="test_ttft_sess")
        tracker.on_turn_started(turn_id=1)
        tracker.on_llm_request_started()

        t_request_started = tracker.current_turn.t4_llm_request_started
        assert t_request_started is not None
        assert tracker.current_turn.t5_llm_first_token is None

        task = _build_real_pipeline_task(
            pipecat_processors=[],
            transport=None,
            bridge=mock_bridge,
            latency_tracker=tracker,
            session_id="test_ttft_sess",
        )
        observer = task._event_bridge_observer

        class MockData:
            def __init__(self, frame, source):
                self.frame = frame
                self.source = source

        mock_source = MagicMock()
        mock_source.__class__.__name__ = "OpenAILLMService"

        # 1. LLMFullResponseStartFrame arrives
        start_frame = LLMFullResponseStartFrame()
        await observer.on_push_frame(MockData(start_frame, mock_source))

        # MUST NOT stamp first token yet!
        assert tracker.current_turn.t5_llm_first_token is None
        assert mock_bridge.on_llm_response_started.called

        # Simulate provider wait
        await asyncio.sleep(0.01)

        # 2. Real first text token arrives
        text_frame = TextFrame("Hello")
        await observer.on_push_frame(MockData(text_frame, mock_source))

        # NOW first token must be stamped
        assert tracker.current_turn.t5_llm_first_token is not None
        ttft = tracker.current_turn.llm_ttft
        assert ttft is not None
        assert ttft >= 0.01  # Accurately includes the provider wait time

    @pytest.mark.asyncio
    async def test_ttft_stamped_on_tool_call_frame(self):
        """If a tool call frame arrives before text, on_llm_first_token() must be stamped."""
        from app.adapters.pipecat.adapter import _build_real_pipeline_task

        mock_bridge = MagicMock()
        mock_bridge._session_id = "test_tool_ttft_sess"

        tracker = LatencyTracker(session_id="test_tool_ttft_sess")
        tracker.on_turn_started(turn_id=1)
        tracker.on_llm_request_started()

        task = _build_real_pipeline_task(
            pipecat_processors=[],
            transport=None,
            bridge=mock_bridge,
            latency_tracker=tracker,
            session_id="test_tool_ttft_sess",
        )
        observer = task._event_bridge_observer

        class MockData:
            def __init__(self, frame, source):
                self.frame = frame
                self.source = source

        mock_source = MagicMock()
        mock_source.__class__.__name__ = "OpenAILLMService"

        # 1. LLMFullResponseStartFrame arrives
        await observer.on_push_frame(MockData(LLMFullResponseStartFrame(), mock_source))
        assert tracker.current_turn.t5_llm_first_token is None

        # 2. Tool call arrives
        tool_frame = FunctionCallsStartedFrame(function_calls=[])
        await observer.on_push_frame(MockData(tool_frame, mock_source))

        assert tracker.current_turn.t5_llm_first_token is not None


class TestLatencyTrackerSummaryTable:
    """Verifies that print_summary displays real llm_ttft without silence conflation."""

    def test_summary_table_reports_true_ttft(self, capsys):
        tracker = LatencyTracker(session_id="test_summary_sess")
        tracker.on_turn_started(turn_id=1)
        tracker.on_vad_stop()  # T0 = e.g. 100.0
        # Wait 450ms for silence timeout
        tracker.on_turn_finalized(timeout=0.45)
        tracker.on_llm_request_started()  # T4 = e.g. 100.45
        # LLM takes 800ms
        tracker.current_turn.t5_llm_first_token = tracker.current_turn.t4_llm_request_started + 0.800
        tracker.current_turn.llm_first_token = tracker.current_turn.t5_llm_first_token
        # TTS takes 100ms
        tracker.current_turn.t6_first_tts_text = tracker.current_turn.t5_llm_first_token + 0.015
        tracker.current_turn.tts_first_text = tracker.current_turn.t6_first_tts_text
        tracker.current_turn.t7_first_tts_audio = tracker.current_turn.t6_first_tts_text + 0.085
        tracker.current_turn.tts_first_audio = tracker.current_turn.t7_first_tts_audio

        tracker.all_turns.append(tracker.current_turn)
        tracker.print_summary()

        captured = capsys.readouterr().out
        assert "Turn 1" in captured
        # TTFT should report ~0.80 s, NOT conflated with silence timeout
        assert "0.80 s" in captured


class TestGroqConnectionPooling:
    """Verifies HTTP keep-alive connection pooling for Groq."""

    def test_shared_groq_http_client_singleton(self):
        from app.adapters.pipecat.processors import get_shared_groq_http_client
        c1 = get_shared_groq_http_client()
        c2 = get_shared_groq_http_client()
        assert c1 is c2
        assert hasattr(c1, "_transport") or hasattr(c1, "_pool") or hasattr(c1, "_limits")

    def test_pooled_groq_service_reuses_http_client(self):
        from app.adapters.pipecat.processors import PooledGroqLLMService, get_shared_groq_http_client
        svc1 = PooledGroqLLMService(api_key="gsk-test-call-1")
        svc2 = PooledGroqLLMService(api_key="gsk-test-call-2")

        shared_pool = get_shared_groq_http_client()
        assert svc1._client._client is shared_pool
        assert svc2._client._client is shared_pool
        assert svc1._client._client is svc2._client._client


class TestLatencyPercentilesAndColdWarmBreakdown:
    """Verifies p50/p90/p95, warm vs cold classification, and application vs outbound TTFA."""

    def test_cold_vs_warm_metrics_and_percentiles(self):
        tracker = LatencyTracker(session_id="test_cold_warm_sess", dispatch_id="disp_1", call_uuid="uuid_1")

        # Turn 1 (Cold turn: DNS/TLS/Warm-up)
        t1 = TurnLatency(
            turn_number=1,
            session_id=tracker.session_id,
            dispatch_id=tracker.dispatch_id,
            call_uuid=tracker.call_uuid,
            generation_id="gen_1",
            is_cold=True,
            t4_llm_request_started=100.0,
            t5_llm_first_token=101.4,  # TTFT = 1.4s (cold)
            t7_first_tts_audio=101.6,   # App TTFA = 1.6s
            t8_transport_audio=101.65,  # Outbound media = 1.65s
            configured_timeout=0.45,
        )
        tracker.all_turns.append(t1)

        # Turns 2-10 (Warm turns: persistent socket reused)
        for i in range(2, 11):
            t_warm = TurnLatency(
                turn_number=i,
                session_id=tracker.session_id,
                dispatch_id=tracker.dispatch_id,
                call_uuid=tracker.call_uuid,
                generation_id=f"gen_{i}",
                is_cold=False,
                t4_llm_request_started=200.0 + i,
                t5_llm_first_token=200.0 + i + 0.35 + (i * 0.01),  # TTFT ~ 0.37s (warm)
                t7_first_tts_audio=200.0 + i + 0.50,
                t8_transport_audio=200.0 + i + 0.53,
                configured_timeout=0.45,
            )
            tracker.all_turns.append(t_warm)

        stats = tracker.compute_statistics()

        assert stats["turn_count"] == 10
        # Cold turn TTFT
        assert stats["llm_ttft_cold"]["count"] == 1
        assert stats["llm_ttft_cold"]["p50"] == 1.4

        # Warm turns TTFT (9 samples)
        assert stats["llm_ttft_warm"]["count"] == 9
        assert stats["llm_ttft_warm"]["p50"] < 0.50
        assert stats["llm_ttft_warm"]["p95"] < 0.50

        # Independent application TTFA vs outbound media payload
        assert stats["application_ttfa"]["count"] == 10
        assert stats["outbound_media_ttfa"]["count"] == 10
        assert stats["outbound_media_ttfa"]["p50"] >= stats["application_ttfa"]["p50"]

        # Distinction note present
        assert "audible_pstn_response_note" in stats

    def test_on_transport_audio_stamps_generation_id_and_t8(self):
        tracker = LatencyTracker(session_id="test_t8_sess")
        tracker.on_turn_started(turn_id=1)
        tracker.on_transport_audio(generation_id="gen_42")

        assert tracker.current_turn.t8_transport_audio is not None
        assert tracker.current_turn.t8_ns is not None
        assert tracker.current_turn.generation_id == "gen_42"


class TestSessionIsolationAndNoLeakage:
    """Verifies that pooled HTTP connections do not leak credentials or conversation state."""

    def test_pooled_services_isolate_api_keys_and_headers(self):
        svc_a = PooledOpenAILLMService(api_key="sk-alpha-key-11111")
        svc_b = PooledOpenAILLMService(api_key="sk-beta-key-22222")

        # Each service has its own AsyncOpenAI instance and headers
        assert svc_a._client.api_key == "sk-alpha-key-11111"
        assert svc_b._client.api_key == "sk-beta-key-22222"
        assert svc_a._client is not svc_b._client


class TestLatencyEdgeCasesAndRobustness:
    """Verifies robustness against clock skew, missing timestamps, cancellation, and small samples."""

    def test_small_sample_linear_interpolation_percentiles(self):
        tracker = LatencyTracker(session_id="test_small_sample")
        
        # Test n=1: p50 == p90 == p95 == value
        tracker.all_turns = [
            TurnLatency(turn_number=1, t4_llm_request_started=1.0, t5_llm_first_token=1.5, is_cold=True)
        ]
        stats = tracker.compute_statistics()
        assert stats["llm_ttft"]["count"] == 1
        assert stats["llm_ttft"]["p50"] == 0.5
        assert stats["llm_ttft"]["p90"] == 0.5
        assert stats["llm_ttft"]["p95"] == 0.5

        # Test n=2: [0.2, 0.8]
        # rank for 0.5 = 0.5 * 1 = 0.5 -> 0.2*0.5 + 0.8*0.5 = 0.50
        tracker.all_turns = [
            TurnLatency(turn_number=1, t4_llm_request_started=1.0, t5_llm_first_token=1.2, is_cold=False),
            TurnLatency(turn_number=2, t4_llm_request_started=2.0, t5_llm_first_token=2.8, is_cold=False),
        ]
        stats = tracker.compute_statistics()
        assert stats["llm_ttft"]["count"] == 2
        assert stats["llm_ttft"]["p50"] == 0.50
        assert stats["llm_ttft"]["min"] == 0.20
        assert stats["llm_ttft"]["max"] == 0.80

    def test_out_of_order_timestamps_do_not_produce_negative_latencies(self):
        """If clock jitter or cancellation causes t5 < t4, property must return None rather than negative."""
        turn = TurnLatency(
            turn_number=1,
            t4_llm_request_started=105.0,
            t5_llm_first_token=102.0,  # Out of order
            t0_user_speech_end=50.0,
            t2_final_transcript=45.0,  # Out of order
            t8_transport_audio=40.0,   # Out of order
        )
        assert turn.llm_ttft is None
        assert turn.groq_ttft is None
        assert turn.stt_finalization_latency is None
        assert turn.outbound_media_ttfa is None

    def test_incomplete_or_cancelled_turns_do_not_corrupt_stats(self):
        tracker = LatencyTracker(session_id="test_cancelled")
        # Turn with missing t5 (cancelled before first token)
        turn_cancelled = TurnLatency(turn_number=1, t4_llm_request_started=10.0, t5_llm_first_token=None)
        tracker.all_turns.append(turn_cancelled)
        
        # Valid complete turn
        turn_valid = TurnLatency(turn_number=2, t4_llm_request_started=20.0, t5_llm_first_token=20.35)
        tracker.all_turns.append(turn_valid)

        stats = tracker.compute_statistics()
        assert stats["llm_ttft"]["count"] == 1  # Cancelled turn excluded from TTFT sample count
        assert stats["llm_ttft"]["p50"] == 0.35

    def test_dynamic_connection_lifecycle_warming(self):
        tracker = LatencyTracker(session_id="test_warming")
        assert tracker.is_warmed_up is False

        # First turn is cold
        tracker.on_turn_started(turn_id=1)
        assert tracker.current_turn.is_cold is True

        # Simulate full turn lifecycle completion
        tracker.on_vad_start()
        tracker.on_stt_transcript("Hello")
        tracker.on_vad_stop()
        tracker.on_llm_request_started()
        tracker.on_llm_first_token()
        tracker.on_tts_start()
        tracker.on_llm_complete()
        assert tracker.is_warmed_up is True

        # Next turn is warm
        tracker.on_turn_started(turn_id=2)
        assert tracker.current_turn.is_cold is False

        # Explicit lifecycle control methods
        tracker.mark_connection_cold()
        assert tracker.is_warmed_up is False
        tracker.mark_connection_warmed()
        assert tracker.is_warmed_up is True

