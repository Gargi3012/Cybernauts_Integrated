import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import (
    TextFrame,
    AudioRawFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from app.adapters.pipecat.language_router import CallTerminationProcessor
from app.adapters.pipecat.sarvam_tts_service import LowLatencyClauseAggregator
from app.adapters.pipecat.turn_guard import ValidatedUserTurnStartStrategy, TurnGuardFilter
from app.adapters.pipecat.llm_filler_processor import DynamicLLMFillerProcessor


# ============================================================================
# 1. Full numeric confirmation reaches TTS (5 chunks, intact digit sequence)
# ============================================================================
@pytest.mark.asyncio
async def test_phone_confirmation_full_numeric_reaches_tts():
    """
    Verify that when the LLM emits a phone confirmation across multiple chunks,
    LowLatencyClauseAggregator emits the preamble for immediate latency, but keeps
    the full 10-digit spaced sequence intact rather than slicing through digits.
    """
    aggregator = LowLatencyClauseAggregator()
    chunks = [
        "Just to",
        " confirm,",
        " your number is 9 2 1",
        " 5 0 2 4 4 0",
        " 1—is that correct?"
    ]
    emitted = []
    for chunk in chunks:
        async for agg in aggregator.aggregate(chunk):
            emitted.append(agg.text)
    final = await aggregator.flush()
    if final:
        emitted.append(final.text)

    # Validate clauses
    assert len(emitted) >= 3
    # Preamble should be emitted early for fast first-byte audio
    assert "Just to confirm," in emitted[0]
    # Digits must be grouped intact without breaking mid-sequence
    full_text = " ".join(emitted)
    assert "9 2 1 5 0 2 4 4 0 1" in full_text
    # Specific digit sequence chunk contains all 10 digits
    digit_chunk = next((c for c in emitted if "9 2 1" in c), None)
    assert digit_chunk is not None
    assert "5 0 2 4 4 0 1" in digit_chunk


# ============================================================================
# 2. All generated audio frames reach transport
# ============================================================================
@pytest.mark.asyncio
async def test_all_generated_audio_frames_reach_transport():
    """
    Verify that all AudioRawFrames pass through CallTerminationProcessor without
    being dropped or blocked before BotStoppedSpeakingFrame.
    """
    shared_state = {"hangup_requested": True}
    processor = CallTerminationProcessor(shared_state=shared_state)
    pushed_frames = []
    async def mock_push(frame, direction=None):
        pushed_frames.append(frame)
    processor.push_frame = mock_push

    audio_frames = [
        AudioRawFrame(audio=b"\x00\x01" * 160, sample_rate=16000, num_channels=1)
        for _ in range(10)
    ]

    for frame in audio_frames:
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

    collected_audio = [f for f in pushed_frames if isinstance(f, AudioRawFrame)]
    assert len(collected_audio) == 10
    # Termination should NOT have started yet because bot is still speaking
    assert not shared_state.get("termination_started")


# ============================================================================
# 3. Numeric confirmation is not interrupted by stray interim noise (e.g. 'You')
# ============================================================================
@pytest.mark.asyncio
async def test_numeric_confirmation_not_interrupted_by_stray_interim_noise():
    """
    Verify that single-word interim acoustic noise ('You', 'Uh') does not trigger
    barge-in interruption, but legitimate barge-in keywords ('Wait', 'Ruko') or
    multi-word speech do trigger barge-in.
    """
    shared_state = {"current_turn_id": 1}
    strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
    strategy.trigger_user_turn_started = AsyncMock()

    # 1. Stray noise during phone confirmation (e.g. line echo 'You')
    noise_frame = InterimTranscriptionFrame(text="You", user_id="user", timestamp="100.0")
    await strategy.process_frame(noise_frame)
    assert not strategy._triggered
    assert not strategy.trigger_user_turn_started.called

    # 2. Another stray noise token 'Uh'
    noise_frame2 = InterimTranscriptionFrame(text="Uh", user_id="user", timestamp="100.2")
    await strategy.process_frame(noise_frame2)
    assert not strategy._triggered
    assert not strategy.trigger_user_turn_started.called

    # 3. Legitimate single-token barge-in keyword 'Wait'
    barge_frame = InterimTranscriptionFrame(text="Wait", user_id="user", timestamp="100.5")
    await strategy.process_frame(barge_frame)
    assert strategy._triggered
    assert strategy.trigger_user_turn_started.called

    # 4. Multi-word interim speech triggers barge-in
    await strategy.reset()
    strategy.trigger_user_turn_started.reset_mock()
    multi_frame = InterimTranscriptionFrame(text="no that is wrong", user_id="user", timestamp="101.0")
    await strategy.process_frame(multi_frame)
    assert strategy._triggered
    assert strategy.trigger_user_turn_started.called


# ============================================================================
# 4. Phone confirmation does not trigger call termination
# ============================================================================
@pytest.mark.asyncio
async def test_phone_confirmation_does_not_trigger_call_termination():
    """
    Verify that AI phone number confirmation questions containing 'confirm' or '?'
    are never misclassified as natural conversation conclusions.
    """
    shared_state = {}
    processor = CallTerminationProcessor(shared_state=shared_state)

    confirmation_text = "Just to confirm, your number is 9 2 1 5 0 2 4 4 0 1—is that correct?"
    await processor.process_frame(TextFrame(confirmation_text), FrameDirection.DOWNSTREAM)
    await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    assert not shared_state.get("termination_requested")
    assert not shared_state.get("hangup_requested")
    assert not shared_state.get("termination_started")


# ============================================================================
# 5. User goodbye triggers termination_requested, goodbye text, BotStoppedSpeakingFrame, single hangup
# ============================================================================
@pytest.mark.asyncio
async def test_user_goodbye_triggers_termination_chain():
    """
    Verify full end-of-call chain:
    User goodbye -> hangup_requested=True -> LLM goodbye text -> BotStoppedSpeakingFrame -> hangup executed.
    """
    with patch("app.adapters.pipecat.language_router._terminate_plivo_carrier_call", new_callable=AsyncMock) as mock_hangup:
        shared_state = {
            "hangup_requested": True,
            "call_id": "test_call_uuid_001",
            "auth_id": "test_auth",
            "auth_token": "test_token",
            "session_id": "sess_001",
            "dispatch_id": "disp_001",
        }
        processor = CallTerminationProcessor(shared_state=shared_state)

        # Bot streams goodbye
        await processor.process_frame(TextFrame("Thank you for your time. Have a great day!"), FrameDirection.DOWNSTREAM)
        await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        assert not shared_state.get("termination_started")

        # Bot finishes speaking goodbye
        await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        assert shared_state.get("termination_started") is True
        assert mock_hangup.called


# ============================================================================
# 6. Natural final goodbye without end_call triggers termination
# ============================================================================
@pytest.mark.asyncio
async def test_natural_final_goodbye_without_end_call_triggers_termination():
    """
    Verify that if the LLM naturally says goodbye without semantic end_call detector,
    CallTerminationProcessor detects the terminal phrase and schedules termination on BotStoppedSpeakingFrame.
    """
    with patch("app.adapters.pipecat.language_router._terminate_plivo_carrier_call", new_callable=AsyncMock) as mock_hangup:
        shared_state = {
            "call_id": "test_call_uuid_002",
            "auth_id": "test_auth",
            "auth_token": "test_token",
        }
        processor = CallTerminationProcessor(shared_state=shared_state)

        await processor.process_frame(TextFrame("Thank you for your time. Have a great day!"), FrameDirection.DOWNSTREAM)
        await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

        assert shared_state.get("termination_requested") is True
        assert shared_state.get("termination_source") == "NATURAL_CONCLUSION"

        await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        assert shared_state.get("termination_started") is True
        assert mock_hangup.called


# ============================================================================
# 7. Normal "thank you for confirming" does not terminate
# ============================================================================
@pytest.mark.asyncio
async def test_normal_thank_you_for_confirming_does_not_terminate():
    """
    Verify that mid-conversation gratitude ("Thank you for confirming your details...")
    is not mistaken for final call closure.
    """
    shared_state = {}
    processor = CallTerminationProcessor(shared_state=shared_state)

    text = "Thank you for confirming your details. Now let me ask one final question."
    await processor.process_frame(TextFrame(text), FrameDirection.DOWNSTREAM)
    await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    assert not shared_state.get("termination_requested")
    assert not shared_state.get("termination_started")


# ============================================================================
# 8. Duplicate termination signals produce exactly one hangup
# ============================================================================
@pytest.mark.asyncio
async def test_duplicate_termination_signals_produce_exactly_one_hangup():
    """
    Verify idempotency: multiple BotStoppedSpeakingFrames or duplicate hangup triggers
    result in exactly ONE Plivo carrier call termination REST call.
    """
    with patch("app.adapters.pipecat.language_router._terminate_plivo_carrier_call", new_callable=AsyncMock) as mock_hangup:
        shared_state = {
            "hangup_requested": True,
            "call_id": "test_call_uuid_003",
            "auth_id": "test_auth",
            "auth_token": "test_token",
        }
        processor = CallTerminationProcessor(shared_state=shared_state)

        # First trigger
        await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        # Duplicate triggers
        await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await processor._execute_hangup(reason="duplicate_call")
        await asyncio.sleep(0.05)

        assert mock_hangup.call_count == 1


# ============================================================================
# 9. Termination state survives until BotStoppedSpeakingFrame
# ============================================================================
@pytest.mark.asyncio
async def test_termination_state_survives_until_bot_stopped_speaking():
    """
    Verify that hangup_requested / termination_requested flags are NOT reset by
    intermediate TTS or audio frames, surviving until BotStoppedSpeakingFrame arrives.
    """
    shared_state = {"hangup_requested": True}
    processor = CallTerminationProcessor(shared_state=shared_state)

    # Intermediate frames flowing during bot goodbye synthesis & playback
    await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(AudioRawFrame(audio=b"\x00" * 320, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await processor.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(TextFrame("Have a great day!"), FrameDirection.DOWNSTREAM)

    assert shared_state.get("hangup_requested") is True
    assert not shared_state.get("termination_started")

    # Final event triggers execution
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert shared_state.get("termination_started") is True


# ============================================================================
# 10. Current call_uuid/correlation is used in REST delete
# ============================================================================
@pytest.mark.asyncio
async def test_current_call_uuid_correlation_used_in_rest_delete():
    """
    Verify that _terminate_plivo_carrier_call receives the exact call_id, session_id,
    and dispatch_id associated with the active call.
    """
    with patch("app.adapters.pipecat.language_router._terminate_plivo_carrier_call", new_callable=AsyncMock) as mock_hangup:
        shared_state = {
            "hangup_requested": True,
            "call_id": "plivo_call_live_777",
            "auth_id": "auth_live_id",
            "auth_token": "auth_live_token",
            "session_id": "session_live_888",
            "dispatch_id": "dispatch_live_999",
            "current_turn_id": 5,
        }
        processor = CallTerminationProcessor(shared_state=shared_state)
        await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)

        mock_hangup.assert_called_once_with(
            "plivo_call_live_777",
            "auth_live_id",
            "auth_live_token",
            session_id="session_live_888",
            dispatch_id="dispatch_live_999",
            turn_id=5,
        )


# ============================================================================
# 11. Previous-call state cannot trigger termination
# ============================================================================
@pytest.mark.asyncio
async def test_previous_call_state_cannot_trigger_termination():
    """
    Verify that a fresh call session starting with clean state cannot be terminated
    by previous-call events or uninitialized flags.
    """
    fresh_shared_state = {
        "call_id": "call_2_fresh",
        "session_id": "session_2_fresh",
    }
    processor = CallTerminationProcessor(shared_state=fresh_shared_state)

    # Standard bot speech in fresh call
    await processor.process_frame(TextFrame("नमस्ते, मैं सारा बोल रही हूँ।"), FrameDirection.DOWNSTREAM)
    await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    assert not fresh_shared_state.get("termination_requested")
    assert not fresh_shared_state.get("hangup_requested")
    assert not fresh_shared_state.get("termination_started")


# ============================================================================
# 12. TurnGuard and DynamicLLMFillerProcessor do not suppress the final goodbye
# ============================================================================
@pytest.mark.asyncio
async def test_turn_guard_and_filler_do_not_suppress_final_goodbye():
    """
    Verify that when ending_call=True, both TurnGuardFilter and DynamicLLMFillerProcessor
    allow the final goodbye response (turn_id <= ending_call_turn_id) to pass through,
    while suppressing any subsequent turns.
    """
    shared_state = {
        "ending_call": True,
        "ending_call_turn_id": 4,
        "current_turn_id": 4,
    }

    # 1. Test TurnGuardFilter
    guard = TurnGuardFilter(shared_state=shared_state)
    guard_pushed = []
    async def mock_guard_push(frame, direction=None):
        guard_pushed.append(frame)
    guard.push_frame = mock_guard_push

    goodbye_frame = TextFrame("Thank you for your time. Have a great day!")
    await guard.process_frame(goodbye_frame, FrameDirection.DOWNSTREAM)
    assert len(guard_pushed) == 1
    assert guard_pushed[0].text == goodbye_frame.text

    # 2. Test DynamicLLMFillerProcessor
    filler_proc = DynamicLLMFillerProcessor(shared_state=shared_state)
    filler_pushed = []
    async def mock_filler_push(frame, direction=None):
        filler_pushed.append(frame)
    filler_proc.push_frame = mock_filler_push

    start_frame = LLMFullResponseStartFrame()
    start_frame._turn_id = 4
    await filler_proc.process_frame(start_frame, FrameDirection.DOWNSTREAM)

    goodbye_frame2 = TextFrame("Thank you for your time. Have a great day!")
    goodbye_frame2._turn_id = 4
    await filler_proc.process_frame(goodbye_frame2, FrameDirection.DOWNSTREAM)

    emitted_texts = [f.text for f in filler_pushed if isinstance(f, TextFrame)]
    assert any("Thank you for your time" in t for t in emitted_texts)

    # 3. Subsequent turn (turn 5) MUST be suppressed
    shared_state["current_turn_id"] = 5
    guard_pushed.clear()
    subsequent_frame = TextFrame("Extra subsequent text")
    await guard.process_frame(subsequent_frame, FrameDirection.DOWNSTREAM)
    assert len(guard_pushed) == 0


# ============================================================================
# 13. TurnGuard does not suppress the second half of a phone confirmation
# ============================================================================
@pytest.mark.asyncio
async def test_turn_guard_does_not_suppress_second_half_of_phone_confirmation():
    """
    Verify that TurnGuardFilter does not suppress streaming chunks belonging to
    the current active turn during a phone confirmation.
    """
    shared_state = {"current_turn_id": 2}
    guard = TurnGuardFilter(shared_state=shared_state)
    pushed_frames = []
    async def mock_push(frame, direction=None):
        pushed_frames.append(frame)
    guard.push_frame = mock_push

    start_frame = LLMFullResponseStartFrame()
    start_frame._turn_id = 2
    await guard.process_frame(start_frame, FrameDirection.DOWNSTREAM)

    # First half
    chunk1 = TextFrame("Just to confirm, your number is 9 2 1")
    chunk1._turn_id = 2
    await guard.process_frame(chunk1, FrameDirection.DOWNSTREAM)

    # Second half
    chunk2 = TextFrame(" 5 0 2 4 4 0 1—is that correct?")
    chunk2._turn_id = 2
    await guard.process_frame(chunk2, FrameDirection.DOWNSTREAM)

    end_frame = LLMFullResponseEndFrame()
    await guard.process_frame(end_frame, FrameDirection.DOWNSTREAM)

    collected_texts = [f.text for f in pushed_frames if isinstance(f, TextFrame)]
    assert len(collected_texts) == 2
    assert "9 2 1" in collected_texts[0]
    assert "5 0 2 4 4 0 1" in collected_texts[1]
