import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.pipeline.processors import ProcessorRole
from app.adapters.pipecat.processors import (
    PipecatProcessorAdapter,
    MockPipecatProcessor,
    create_pipecat_processor,
    _create_mock_processor
)


def test_pipecat_processor_adapter():
    mock_inner = MagicMock()
    adapter = PipecatProcessorAdapter("test_processor", mock_inner)
    assert adapter.name == "test_processor"
    assert adapter.get_processor() is mock_inner


def test_create_mock_processor():
    mock_stt = _create_mock_processor(ProcessorRole.STT)
    assert mock_stt.name == "MockSTT"
    assert isinstance(mock_stt, MockPipecatProcessor)

    mock_llm = _create_mock_processor(ProcessorRole.LLM)
    assert mock_llm.name == "MockLLM"


@patch("app.adapters.pipecat.processors._create_real_processor")
def test_create_pipecat_processor_success(mock_create_real):
    """Test factory when pipecat-ai is installed (mocked)."""
    mock_real = MagicMock()
    mock_create_real.return_value = mock_real

    result = create_pipecat_processor(ProcessorRole.STT, {})
    assert result is mock_real
    mock_create_real.assert_called_once_with(ProcessorRole.STT, {}, "livekit")


@patch("app.adapters.pipecat.processors._create_real_processor", side_effect=ImportError("No pipecat"))
def test_create_pipecat_processor_fallback(mock_create_real):
    """Test factory fallback to mock when pipecat-ai is missing."""
    result = create_pipecat_processor(ProcessorRole.STT, {})
    assert isinstance(result, MockPipecatProcessor)
    assert result.name == "MockSTT"
    mock_create_real.assert_called_once_with(ProcessorRole.STT, {}, "livekit")


@patch("app.config.DEEPGRAM_API_KEY", "test_key")
def test_create_real_processor_stt_missing_pipecat():
    """Test real STT processor creation raises ImportError in CI where pipecat is missing."""
    try:
        from pipecat.services.deepgram.stt import DeepgramSTTService
        pipecat_installed = True
    except ImportError:
        pipecat_installed = False

    if not pipecat_installed:
        with pytest.raises(ImportError):
            from app.adapters.pipecat.processors import _create_real_processor
            _create_real_processor(ProcessorRole.STT, {})
    else:
        from app.adapters.pipecat.processors import _create_real_processor
        res = _create_real_processor(ProcessorRole.STT, {})
        assert res is not None


@pytest.mark.asyncio
async def test_resilient_tts_processor_fallback_and_none_resilience():
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import TextFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = MagicMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = MagicMock()

    # When fallback factory returns None
    processor = ResilientTTSProcessor(mock_primary, lambda: None)
    await processor.trigger_tts_fallback("test error")
    assert processor.fallback_active is False
    assert processor.active_tts is mock_primary

    # When fallback factory returns a valid fallback processor
    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.process_frame = MagicMock()
    mock_fallback._prev = None
    mock_fallback.push_error_frame = MagicMock()
    mock_fallback._FrameProcessor__started = False

    processor2 = ResilientTTSProcessor(mock_primary, lambda: mock_fallback)
    await processor2.trigger_tts_fallback("429 Rate limit")
    assert processor2.fallback_active is True
    assert processor2.active_tts is mock_fallback


@pytest.mark.asyncio
async def test_resilient_tts_normal_success():
    """Case 1: Primary Cartesia TTS succeeds normally."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import TextFrame, StartFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_fallback_factory = MagicMock()
    processor = ResilientTTSProcessor(mock_primary, mock_fallback_factory)

    # Deliver StartFrame
    start_frame = StartFrame()
    await processor.process_frame(start_frame, FrameDirection.DOWNSTREAM)
    assert processor._start_frame is start_frame
    mock_primary.process_frame.assert_called_with(start_frame, FrameDirection.DOWNSTREAM)

    # Deliver TextFrame
    text_frame = TextFrame(text="Hello from Cartesia")
    await processor.process_frame(text_frame, FrameDirection.DOWNSTREAM)
    mock_primary.process_frame.assert_called_with(text_frame, FrameDirection.DOWNSTREAM)

    assert processor.fallback_active is False
    assert processor.active_tts is mock_primary
    mock_fallback_factory.assert_not_called()


@pytest.mark.asyncio
async def test_resilient_tts_provider_error_intercept_triggers_fallback():
    """Case 2: Primary Cartesia raises a concurrency limit or provider error."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import ErrorFrame, TextFrame, StartFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.process_frame = AsyncMock()
    mock_fallback.setup = AsyncMock()
    mock_fallback._prev = None

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_fallback)
    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

    # Simulate primary Cartesia pushing 429 concurrency limit error
    error_frame = ErrorFrame(error="Cartesia WebSocket 429: Concurrency limit reached")
    await mock_primary.push_error_frame(error_frame)

    assert processor.fallback_active is True
    assert processor.active_tts is mock_fallback


@pytest.mark.asyncio
async def test_resilient_tts_fallback_factory_returns_none():
    """Case 3: fallback_factory returns None."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    processor = ResilientTTSProcessor(mock_primary, lambda: None)
    with patch.object(processor, "push_error", new_callable=AsyncMock) as mock_push_err:
        await processor.trigger_tts_fallback("Simulated error")
        assert processor.fallback_active is False
        assert processor.active_tts is mock_primary
        mock_push_err.assert_called_once()


@pytest.mark.asyncio
async def test_resilient_tts_fallback_factory_raises_exception():
    """Case 4: fallback_factory raises an exception."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    def broken_factory():
        raise ValueError("SARVAM_API_KEY is not configured")

    processor = ResilientTTSProcessor(mock_primary, broken_factory)
    with patch.object(processor, "push_error", new_callable=AsyncMock) as mock_push_err:
        await processor.trigger_tts_fallback("Primary error")
        assert processor.fallback_active is False
        assert processor.active_tts is mock_primary
        mock_push_err.assert_called_once()


@pytest.mark.asyncio
async def test_resilient_tts_fallback_instance_fails_initialization():
    """Case 5: The fallback instance fails during setup / initialization."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_broken_fallback = MagicMock(spec=FrameProcessor)
    async def broken_setup(setup):
        raise RuntimeError("Fallback network connection failed during setup")
    mock_broken_fallback.setup = broken_setup

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_broken_fallback)
    with patch.object(processor, "push_error", new_callable=AsyncMock) as mock_push_err:
        await processor.trigger_tts_fallback("Primary error")
        # Ensure fallback_active was reset to False and active_tts reverted to primary
        assert processor.fallback_active is False
        assert processor.active_tts is mock_primary
        mock_push_err.assert_called_once()


@pytest.mark.asyncio
async def test_resilient_tts_fallback_not_ready_fails_safely():
    """Case 6: Fallback instance is valid but not ready to process frames (raises during start replay)."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import StartFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_not_ready = MagicMock(spec=FrameProcessor)
    mock_not_ready.setup = AsyncMock()
    mock_not_ready.process_frame = AsyncMock(side_effect=RuntimeError("Engine not ready"))

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_not_ready)
    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

    with patch.object(processor, "push_error", new_callable=AsyncMock) as mock_push_err:
        await processor.trigger_tts_fallback("Primary failed")
        assert processor.fallback_active is False
        assert processor.active_tts is mock_primary
        mock_push_err.assert_called_once()


@pytest.mark.asyncio
async def test_resilient_tts_replays_pending_turn_frames_to_fallback():
    """Case 7: Fallback receives pending turn text frames after primary failure."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import StartFrame, LLMFullResponseStartFrame, TextFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.setup = AsyncMock()
    fallback_received_frames = []
    async def fallback_process(frame, direction=None):
        fallback_received_frames.append(frame)
    mock_fallback.process_frame = fallback_process
    mock_fallback._prev = None

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_fallback)
    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

    # Deliver turn start and text frame
    turn_start = LLMFullResponseStartFrame()
    text_1 = TextFrame(text="Hello, this is Flowiz.")
    await processor.process_frame(turn_start, FrameDirection.DOWNSTREAM)
    await processor.process_frame(text_1, FrameDirection.DOWNSTREAM)

    # Now trigger fallback
    await processor.trigger_tts_fallback("Simulated Cartesia disconnect")

    assert processor.fallback_active is True
    assert processor.active_tts is mock_fallback
    # Verify StartFrame, turn_start, and text_1 were replayed onto fallback
    assert any(isinstance(f, StartFrame) for f in fallback_received_frames)
    assert any(isinstance(f, LLMFullResponseStartFrame) for f in fallback_received_frames)
    assert any(isinstance(f, TextFrame) and f.text == "Hello, this is Flowiz." for f in fallback_received_frames)


@pytest.mark.asyncio
async def test_resilient_tts_interruption_clears_pending_replay():
    """Case 8: Interruption clears pending turn frames so cancelled speech is not replayed."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import StartFrame, LLMFullResponseStartFrame, TextFrame, InterruptionFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.setup = AsyncMock()
    fallback_received = []
    async def fallback_process(frame, direction=None):
        fallback_received.append(frame)
    mock_fallback.process_frame = fallback_process

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_fallback)
    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(TextFrame(text="Speech to be interrupted"), FrameDirection.DOWNSTREAM)

    # User interrupts!
    await processor.process_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
    assert len(processor._current_turn_frames) == 0

    # Now trigger fallback
    await processor.trigger_tts_fallback("Error after interruption")
    # Verify cancelled text was NOT replayed onto fallback
    assert not any(isinstance(f, TextFrame) for f in fallback_received)


@pytest.mark.asyncio
async def test_resilient_tts_unlinks_primary_after_fallback():
    """Case 9: Primary TTS is unlinked from _next so late Cartesia chunks cannot leak downstream."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import StartFrame

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary._next = None
    mock_primary.push_error_frame = AsyncMock()
    mock_primary.link = MagicMock(side_effect=lambda next_p: setattr(mock_primary, "_next", next_p))

    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.process_frame = AsyncMock()
    mock_fallback.setup = AsyncMock()
    mock_fallback._next = None
    mock_fallback.link = MagicMock(side_effect=lambda next_p: setattr(mock_fallback, "_next", next_p))

    downstream_proc = MagicMock(spec=FrameProcessor)

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_fallback)
    processor.link(downstream_proc)
    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

    assert mock_primary._next is downstream_proc

    # Trigger fallback
    await processor.trigger_tts_fallback("Cartesia failed")

    # Primary TTS must be disconnected from downstream to isolate late chunks
    assert mock_primary._next is None
    assert mock_fallback._next is downstream_proc


@pytest.mark.asyncio
async def test_resilient_tts_repeated_errors_no_recursion():
    """Case 10: Repeated errors when fallback is already active do not recurse or fail."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.push_error_frame = AsyncMock()

    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.process_frame = AsyncMock()
    mock_fallback.setup = AsyncMock()

    factory_calls = 0
    def counting_factory():
        nonlocal factory_calls
        factory_calls += 1
        return mock_fallback

    processor = ResilientTTSProcessor(mock_primary, counting_factory)
    await processor.trigger_tts_fallback("First error")
    assert processor.fallback_active is True
    assert factory_calls == 1

    # Trigger again with second error
    await processor.trigger_tts_fallback("Second error")
    assert factory_calls == 1  # No duplicate fallback trigger


@pytest.mark.asyncio
async def test_resilient_tts_per_session_isolation():
    """Case 11: Concurrent calls maintain complete isolation."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor

    # Call A
    mock_primary_a = MagicMock(spec=FrameProcessor)
    mock_primary_a.process_frame = AsyncMock()
    mock_primary_a._prev = None
    mock_primary_a.push_error_frame = AsyncMock()
    mock_fb_a = MagicMock(spec=FrameProcessor)
    mock_fb_a.process_frame = AsyncMock()
    mock_fb_a.setup = AsyncMock()
    call_a_proc = ResilientTTSProcessor(mock_primary_a, lambda: mock_fb_a)

    # Call B
    mock_primary_b = MagicMock(spec=FrameProcessor)
    mock_primary_b.process_frame = AsyncMock()
    mock_primary_b._prev = None
    mock_primary_b.push_error_frame = AsyncMock()
    mock_fb_b = MagicMock(spec=FrameProcessor)
    mock_fb_b.process_frame = AsyncMock()
    mock_fb_b.setup = AsyncMock()
    call_b_proc = ResilientTTSProcessor(mock_primary_b, lambda: mock_fb_b)

    # Call A fails over to fallback
    await call_a_proc.trigger_tts_fallback("Call A 429 limit")
    assert call_a_proc.fallback_active is True
    assert call_a_proc.active_tts is mock_fb_a

    # Call B remains on primary Cartesia unaffected
    assert call_b_proc.fallback_active is False
    assert call_b_proc.active_tts is mock_primary_b


@pytest.mark.asyncio
async def test_resilient_tts_cleanup_both_providers():
    """Case 12: Cleanup safely closes both active and primary processors."""
    from app.adapters.pipecat.processors import ResilientTTSProcessor
    from pipecat.processors.frame_processor import FrameProcessor

    mock_primary = MagicMock(spec=FrameProcessor)
    mock_primary.process_frame = AsyncMock()
    mock_primary._prev = None
    mock_primary.cleanup = AsyncMock()
    mock_primary.push_error_frame = AsyncMock()

    mock_fallback = MagicMock(spec=FrameProcessor)
    mock_fallback.process_frame = AsyncMock()
    mock_fallback.setup = AsyncMock()
    mock_fallback.cleanup = AsyncMock()

    processor = ResilientTTSProcessor(mock_primary, lambda: mock_fallback)
    await processor.trigger_tts_fallback("Error triggering fallback")

    await processor.cleanup()
    mock_primary.cleanup.assert_called_once()
    mock_fallback.cleanup.assert_called_once()



