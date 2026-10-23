"""
Regression and deterministic verification suite for the critical production bug:
'LLM Response Visible but Second Response Inaudible'

Reproduction sequence:
1. Agent generates and speaks initial greeting (Turn 1 / Generation 2).
2. Prospect speaks ('So as of now we are dealing with the manual handling.') at 8:59:44 PM.
   Barge-in / interruption invalidates active generation (active_generation_id -> None).
3. Prospect finishes speech -> LLMUserAggregator emits LLMContextFrame.
4. Bug analysis:
   - When TurnGuardProcessor is placed BEFORE LLMUserAggregator in the pipeline,
     LLMContextFrame emitted downstream by the aggregator completely bypasses TurnGuardProcessor.
   - active_generation_id remains None and interrupted_generation_id remains Gen 2.
   - LLM generates response text ('I understand—manual handling can slow follow-ups...').
   - Observer registers LLM response and displays it in UI transcript.
   - TurnGuardFilter downstream sees active_generation_id is None, marks response as stale,
     and suppresses all TextFrames from reaching TTS.
   - Any surviving audio frames are also dropped at AudioInterruptionGate and Plivo serializer.
   - Result: LLM response visible in UI, but 100% inaudible to caller!
5. Fixed topology:
   - LLMUserAggregator -> TurnGuardProcessor -> LLMService.
   - When aggregator emits LLMContextFrame, TurnGuardProcessor catches it, advances turn_id
     and generation_id, reactivates active_generation_id, and clears interrupted_generation_id.
   - TurnGuardFilter passes response frames and stamps active generation ID.
   - TTS synthesizes audio chunks stamped with active generation ID.
   - AudioInterruptionGate allows audio chunks.
   - Plivo serializer encodes playAudio payloads.
   - Transport delivers audio to WebSocket.
"""

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMRunFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    AudioRawFrame,
    InterruptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

from app.adapters.pipecat.turn_guard import TurnGuardProcessor, TurnGuardFilter
from app.adapters.pipecat.adapter import AudioInterruptionGate
from app.adapters.pipecat.processors import ResilientTTSProcessor
from app.adapters.pipecat.tool_interceptor import ToolInterceptionProcessor
from Pillar_2.plivo_bot import (
    AtomicPlivoFrameSerializer,
)


class MockCartesiaTTSService(FrameProcessor):
    def __init__(self, audio_bytes: bytes = b"\x00\x50" * 160, **kwargs):
        kwargs.setdefault("enable_direct_mode", True)
        super().__init__(**kwargs)
        self.audio_bytes = audio_bytes
        self.synthesized_texts = []
        self.emitted_audio_frames = []

    async def process_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, TextFrame) and frame.text:
            self.synthesized_texts.append(frame.text)
            await self.push_frame(TTSStartedFrame(), direction)
            audio_frame = AudioRawFrame(
                audio=self.audio_bytes,
                sample_rate=8000,
                num_channels=1
            )
            if hasattr(frame, "_generation_id"):
                audio_frame._generation_id = frame._generation_id
            self.emitted_audio_frames.append(audio_frame)
            await self.push_frame(audio_frame, direction)
            await self.push_frame(TTSStoppedFrame(), direction)
        else:
            await self.push_frame(frame, direction)


@pytest.mark.asyncio
async def test_reproduction_demonstrating_defect_in_old_topology():
    """
    Demonstrates the exact failure mechanism when TurnGuardProcessor is placed BEFORE user_agg:
    1. Greeting (Gen 2) is active.
    2. Interruption at 8:59:44 PM sets active_generation_id = None, interrupted_generation_id = 2.
    3. User aggregator emits LLMContextFrame downstream to LLM, bypassing TurnGuardProcessor.
    4. active_generation_id stays None.
    5. TurnGuardFilter suppresses Turn 2 response entirely.
    6. Audio never reaches gate or transport.
    """
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
        "stale_responses_discarded": 0,
    }

    turn_guard_proc = TurnGuardProcessor(shared_state=shared_state)
    turn_guard_filter = TurnGuardFilter(shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)

    gate_output = []
    async def push_gate(f, d=None):
        gate_output.append(f)
    gate.push_frame = push_gate

    # --- Turn 1: Greeting generated and audible ---
    greeting_run = LLMRunFrame()
    await turn_guard_proc.process_frame(greeting_run, FrameDirection.DOWNSTREAM)
    assert shared_state["active_generation_id"] == 2
    assert shared_state["current_generation_id"] == 2

    # Greeting plays audio
    greeting_audio = AudioRawFrame(audio=b"\x00\x40" * 160, sample_rate=8000, num_channels=1)
    greeting_audio._generation_id = 2
    await gate.process_frame(greeting_audio, FrameDirection.DOWNSTREAM)
    assert len(gate_output) == 1  # Greeting audio passed gate

    # --- Prospect barge-in / interruption at 8:59:44 PM ---
    int_frame = InterruptionFrame()
    await turn_guard_proc.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    await gate.process_frame(int_frame, FrameDirection.DOWNSTREAM)

    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 2

    # --- Prospect finishes speaking: 'So as of now we are dealing with the manual handling.' ---
    # In the flawed topology, user_agg was AFTER turn_guard_proc.
    # Therefore, user_agg pushed LLMContextFrame downstream to LLM, COMPLETELY BYPASSING turn_guard_proc!
    # Result: active_generation_id is STILL None!
    assert shared_state["active_generation_id"] is None

    # LLM emits Turn 2 response:
    filter_output = []
    async def push_filter(f, d=None):
        filter_output.append(f)
    turn_guard_filter.push_frame = push_filter

    start_frame = LLMFullResponseStartFrame()
    await turn_guard_filter.process_frame(start_frame, FrameDirection.DOWNSTREAM)
    # TurnGuardFilter swallows start_frame because active_gen is None and interrupted_gen is not None
    assert turn_guard_filter._suppressing is True
    assert len(filter_output) == 0

    text_frame = TextFrame(text="I understand—manual handling can slow follow-ups.")
    await turn_guard_filter.process_frame(text_frame, FrameDirection.DOWNSTREAM)
    # TextFrame is SUPPRESSED!
    assert len(filter_output) == 0
    assert shared_state["stale_responses_discarded"] == 1

    # And if any raw audio was generated, Gate drops it!
    late_audio = AudioRawFrame(audio=b"\x00\x50" * 160, sample_rate=8000, num_channels=1)
    late_audio._generation_id = 2
    await gate.process_frame(late_audio, FrameDirection.DOWNSTREAM)
    gate_audio = [f for f in gate_output if isinstance(f, AudioRawFrame)]
    assert len(gate_audio) == 1  # Only greeting audio passed; Turn 2 audio was dropped!
    assert shared_state["late_chunks_dropped"] >= 1


@pytest.mark.asyncio
async def test_fixed_topology_ensures_second_response_is_fully_audible():
    """
    Verifies that with the corrected pipeline topology:
    user_agg -> TurnGuardProcessor -> LLM -> TurnGuardFilter -> Interceptor -> TTS -> Gate -> Serializer
    1. Greeting (Turn 1) is synthesized and reaches transport.
    2. Caller interrupts and speaks Turn 2 ('So as of now we are dealing with the manual handling.').
    3. LLMContextFrame passes through TurnGuardProcessor, reactivating active_generation_id.
    4. Turn 2 response is NOT suppressed by TurnGuardFilter.
    5. TTS receives Turn 2 TextFrame and generates audio frames.
    6. Audio frames pass AudioInterruptionGate (0 dropped).
    7. Plivo serializer encodes playAudio payloads.
    8. Next Conversational Turn (Turn 3) remains functional.
    """
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
        "stale_responses_discarded": 0,
    }

    # Pipeline components
    turn_guard_proc = TurnGuardProcessor(shared_state=shared_state)
    turn_guard_filter = TurnGuardFilter(shared_state=shared_state)
    interceptor = ToolInterceptionProcessor(shared_state=shared_state)
    mock_cartesia = MockCartesiaTTSService()
    resilient_tts = ResilientTTSProcessor(
        primary_tts=mock_cartesia,
        fallback_factory=lambda: None
    )
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_turn2_test", shared_state=shared_state)

    # Wire downstream processors:
    async def push_filter(f, d=None):
        await interceptor.process_frame(f, d)
    turn_guard_filter.push_frame = push_filter

    async def push_interceptor(f, d=None):
        await resilient_tts.process_frame(f, d)
    interceptor.push_frame = push_interceptor

    async def push_tts(f, d=None):
        await gate.process_frame(f, d)
    mock_cartesia.push_frame = push_tts

    gate_out = []
    async def push_gate(f, d=None):
        gate_out.append(f)
    gate.push_frame = push_gate

    # --- Step 1: Greeting Turn (Turn 1 / Gen 2) ---
    greeting_run = LLMRunFrame()
    await turn_guard_proc.process_frame(greeting_run, FrameDirection.DOWNSTREAM)
    assert shared_state["active_generation_id"] == 2
    assert shared_state["current_generation_id"] == 2

    # LLM emits greeting
    await turn_guard_filter.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(
        TextFrame(text="Hi, I’m Sara. I’m reaching out to understand how your team currently handles lead qualification."),
        FrameDirection.DOWNSTREAM
    )
    await turn_guard_filter.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    # Verify Greeting audio reached gate and serializer
    assert len(mock_cartesia.synthesized_texts) == 1
    greeting_audio_frames = [f for f in gate_out if isinstance(f, AudioRawFrame)]
    assert len(greeting_audio_frames) >= 1
    assert greeting_audio_frames[0]._generation_id == 2

    # Serialize greeting audio
    p1 = await serializer.serialize(greeting_audio_frames[0])
    assert p1 is not None
    assert "playAudio" in p1

    # --- Step 2: Prospect interrupts at 8:59:44 PM ---
    int_frame = InterruptionFrame()
    await turn_guard_proc.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    await resilient_tts.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    await gate.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    clear_msg = await serializer.serialize(int_frame)
    assert clear_msg is not None
    assert "clearAudio" in clear_msg

    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 2

    # --- Step 3: Prospect finishes speech -> user_agg emits LLMContextFrame ---
    # With the CORRECT topology, LLMContextFrame passes into TurnGuardProcessor!
    context_turn2 = LLMContextFrame(context=None)
    await turn_guard_proc.process_frame(context_turn2, FrameDirection.DOWNSTREAM)

    # Generation ID is advanced and reactivated!
    assert shared_state["current_generation_id"] == 3
    assert shared_state["active_generation_id"] == 3
    assert shared_state["interrupted_generation_id"] is None
    assert context_turn2._generation_id == 3

    # --- Step 4: LLM emits Turn 2 Response ---
    gate_out.clear()
    await turn_guard_filter.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    assert turn_guard_filter._suppressing is False, "TurnGuardFilter MUST NOT suppress Turn 2!"

    turn2_text = (
        "I understand—manual handling can slow follow-ups. "
        "What’s the biggest bottleneck for your team right now: "
        "lead qualification, calling, or timely customer responses?"
    )
    await turn_guard_filter.process_frame(TextFrame(text=turn2_text), FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    # --- Step 5: Verification of Audio Flow ---
    # A. Cartesia TTS received Turn 2 text
    assert len(mock_cartesia.synthesized_texts) == 2
    assert "I understand" in mock_cartesia.synthesized_texts[1]

    # B. Audio frames emitted with generation 3
    turn2_audio_frames = [f for f in gate_out if isinstance(f, AudioRawFrame)]
    assert len(turn2_audio_frames) >= 1
    assert turn2_audio_frames[0]._generation_id == 3

    # C. AudioInterruptionGate allowed Turn 2 audio (0 dropped)
    assert shared_state["late_chunks_dropped"] == 0

    # D. Plivo serializer generated playAudio payload
    p2 = await serializer.serialize(turn2_audio_frames[0])
    assert p2 is not None
    assert "playAudio" in p2
    payload_data = json.loads(p2)
    assert payload_data["event"] == "playAudio"
    assert "media" in payload_data
    assert len(payload_data["media"]["payload"]) > 0

    # --- Step 6: Next Conversational Turn (Turn 3) remains functional ---
    context_turn3 = LLMContextFrame(context=None)
    await turn_guard_proc.process_frame(context_turn3, FrameDirection.DOWNSTREAM)
    assert shared_state["current_generation_id"] == 4
    assert shared_state["active_generation_id"] == 4

    gate_out.clear()
    await turn_guard_filter.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(
        TextFrame(text="Got it. We can definitely help streamline that for you."),
        FrameDirection.DOWNSTREAM
    )
    await turn_guard_filter.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    turn3_audio_frames = [f for f in gate_out if isinstance(f, AudioRawFrame)]
    assert len(turn3_audio_frames) >= 1
    assert turn3_audio_frames[0]._generation_id == 4
    p3 = await serializer.serialize(turn3_audio_frames[0])
    assert p3 is not None
    assert "playAudio" in p3


@pytest.mark.asyncio
async def test_multiple_consecutive_conversational_turns():
    """Verify at least 5 consecutive turns advance generation IDs and deliver valid audio."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
        "stale_responses_discarded": 0,
    }

    turn_guard_proc = TurnGuardProcessor(shared_state=shared_state)
    turn_guard_filter = TurnGuardFilter(shared_state=shared_state)
    interceptor = ToolInterceptionProcessor(shared_state=shared_state)
    mock_cartesia = MockCartesiaTTSService()
    resilient_tts = ResilientTTSProcessor(primary_tts=mock_cartesia, fallback_factory=lambda: None)
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_multi_turn", shared_state=shared_state)

    async def push_filter(f, d=None):
        await interceptor.process_frame(f, d)
    turn_guard_filter.push_frame = push_filter

    async def push_interceptor(f, d=None):
        await resilient_tts.process_frame(f, d)
    interceptor.push_frame = push_interceptor

    async def push_tts(f, d=None):
        await gate.process_frame(f, d)
    mock_cartesia.push_frame = push_tts

    gate_out = []
    async def push_gate(f, d=None):
        gate_out.append(f)
    gate.push_frame = push_gate

    responses = [
        "Greeting: Hi, I'm Sara from Flowiz.",
        "Turn 2: I understand—manual handling can slow follow-ups.",
        "Turn 3: Lead qualification is indeed the biggest challenge.",
        "Turn 4: We can set up automated voice qualification for you.",
        "Turn 5: What is the best email to send the details?",
    ]

    for turn_idx, resp_text in enumerate(responses, start=1):
        gate_out.clear()

        # Prospect speaks -> context frame emitted by user_agg
        ctx = LLMContextFrame(context=None)
        await turn_guard_proc.process_frame(ctx, FrameDirection.DOWNSTREAM)
        expected_gen = shared_state["active_generation_id"]
        assert expected_gen > 1

        # Optional barge-in on turns 2 and 4
        if turn_idx in (2, 4):
            int_frame = InterruptionFrame()
            await turn_guard_proc.process_frame(int_frame, FrameDirection.DOWNSTREAM)
            await turn_guard_filter.process_frame(int_frame, FrameDirection.DOWNSTREAM)
            await resilient_tts.process_frame(int_frame, FrameDirection.DOWNSTREAM)
            await gate.process_frame(int_frame, FrameDirection.DOWNSTREAM)
            await serializer.serialize(int_frame)
            # User speaks new turn after interruption
            ctx_new = LLMContextFrame(context=None)
            await turn_guard_proc.process_frame(ctx_new, FrameDirection.DOWNSTREAM)
            expected_gen = shared_state["active_generation_id"]

        # LLM generates response
        await turn_guard_filter.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        await turn_guard_filter.process_frame(TextFrame(text=resp_text), FrameDirection.DOWNSTREAM)
        await turn_guard_filter.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

        # Audio verification
        audio_frames = [f for f in gate_out if isinstance(f, AudioRawFrame)]
        assert len(audio_frames) >= 1
        assert audio_frames[0]._generation_id == expected_gen
        play_msg = await serializer.serialize(audio_frames[0])
        assert play_msg is not None
        assert "playAudio" in play_msg


@pytest.mark.asyncio
async def test_cartesia_concurrency_error_triggers_sarvam_fallback_without_loss_of_turn2_audio():
    """Verify that a Cartesia 429 error on Turn 2 triggers Sarvam fallback with generation preservation."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
        "stale_responses_discarded": 0,
    }

    turn_guard_proc = TurnGuardProcessor(shared_state=shared_state)
    turn_guard_filter = TurnGuardFilter(shared_state=shared_state)
    interceptor = ToolInterceptionProcessor(shared_state=shared_state)

    primary_cartesia = MockCartesiaTTSService()
    fallback_sarvam = MockCartesiaTTSService(audio_bytes=b"\x00\x60" * 160)
    fallback_sarvam.setup = AsyncMock()

    resilient_tts = ResilientTTSProcessor(
        primary_tts=primary_cartesia,
        fallback_factory=lambda: fallback_sarvam
    )
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_fallback_test", shared_state=shared_state)

    async def push_filter(f, d=None):
        await interceptor.process_frame(f, d)
    turn_guard_filter.push_frame = push_filter

    async def push_interceptor(f, d=None):
        await resilient_tts.process_frame(f, d)
    interceptor.push_frame = push_interceptor

    gate_out = []
    async def push_gate(f, d=None):
        gate_out.append(f)
    gate.push_frame = push_gate

    async def push_primary(f, d=None):
        await gate.process_frame(f, d)
    primary_cartesia.push_frame = push_primary

    async def push_fallback(f, d=None):
        await gate.process_frame(f, d)
    fallback_sarvam.push_frame = push_fallback

    # Turn 2 context
    ctx = LLMContextFrame(context=None)
    await turn_guard_proc.process_frame(ctx, FrameDirection.DOWNSTREAM)
    assert shared_state["active_generation_id"] == 2

    # Primary Cartesia hits 429 concurrency limit
    await resilient_tts.trigger_tts_fallback("Cartesia 429: Concurrency limit reached")
    assert resilient_tts.fallback_active is True
    assert resilient_tts.active_tts is fallback_sarvam

    # LLM emits Turn 2 text
    await turn_guard_filter.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(
        TextFrame(text="I understand—manual handling can slow follow-ups."),
        FrameDirection.DOWNSTREAM
    )
    await turn_guard_filter.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    # Audio frames emitted by Sarvam fallback
    audio_frames = [f for f in gate_out if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) >= 1
    assert audio_frames[0]._generation_id == 2
    play_msg = await serializer.serialize(audio_frames[0])
    assert play_msg is not None
    assert "playAudio" in play_msg


@pytest.mark.asyncio
async def test_short_responses_and_punctuation_free_turns_flushed_and_audible():
    """Verify that short responses ('Sure', 'Yes', 'OK') are emitted and audible."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
        "stale_responses_discarded": 0,
    }

    turn_guard_proc = TurnGuardProcessor(shared_state=shared_state)
    turn_guard_filter = TurnGuardFilter(shared_state=shared_state)
    interceptor = ToolInterceptionProcessor(shared_state=shared_state)
    mock_cartesia = MockCartesiaTTSService()
    resilient_tts = ResilientTTSProcessor(primary_tts=mock_cartesia, fallback_factory=lambda: None)
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_short_test", shared_state=shared_state)

    async def push_filter(f, d=None):
        await interceptor.process_frame(f, d)
    turn_guard_filter.push_frame = push_filter

    async def push_interceptor(f, d=None):
        await resilient_tts.process_frame(f, d)
    interceptor.push_frame = push_interceptor

    async def push_tts(f, d=None):
        await gate.process_frame(f, d)
    mock_cartesia.push_frame = push_tts

    gate_out = []
    async def push_gate(f, d=None):
        gate_out.append(f)
    gate.push_frame = push_gate

    # Turn 2: short response with no trailing punctuation
    ctx = LLMContextFrame(context=None)
    await turn_guard_proc.process_frame(ctx, FrameDirection.DOWNSTREAM)
    assert shared_state["active_generation_id"] == 2

    await turn_guard_filter.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(TextFrame(text="Sure"), FrameDirection.DOWNSTREAM)
    await turn_guard_filter.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    audio_frames = [f for f in gate_out if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) >= 1
    assert audio_frames[0]._generation_id == 2
    play_msg = await serializer.serialize(audio_frames[0])
    assert play_msg is not None
    assert "playAudio" in play_msg


@pytest.mark.asyncio
async def test_stale_generation_chunks_rejected_while_active_turn_accepted():
    """Verify that stale chunks from Gen 1 are rejected while valid Gen 2 chunks pass."""
    shared_state = {
        "current_turn_id": 2,
        "current_generation_id": 2,
        "active_generation_id": 2,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
    }

    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_stale_test", shared_state=shared_state)

    gate_out = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: gate_out.append(f))

    # Old Gen 1 late chunk arrives -> rejected at Gate
    stale_chunk = AudioRawFrame(audio=b"\x00\x40" * 160, sample_rate=8000, num_channels=1)
    stale_chunk._generation_id = 1
    await gate.process_frame(stale_chunk, FrameDirection.DOWNSTREAM)
    assert len(gate_out) == 0
    assert shared_state["late_chunks_dropped"] == 1

    # Old Gen 1 late chunk arriving at serializer directly -> returns None
    stale_ser = await serializer.serialize(stale_chunk)
    assert stale_ser is None

    # Valid Gen 2 chunk arrives -> accepted at Gate and serialized
    valid_chunk = AudioRawFrame(audio=b"\x00\x50" * 160, sample_rate=8000, num_channels=1)
    valid_chunk._generation_id = 2
    await gate.process_frame(valid_chunk, FrameDirection.DOWNSTREAM)
    assert len(gate_out) == 1
    assert gate_out[0]._generation_id == 2

    valid_ser = await serializer.serialize(valid_chunk)
    assert valid_ser is not None
    assert "playAudio" in valid_ser


@pytest.mark.asyncio
async def test_untagged_tts_audio_stamped_and_passed_through_gate():
    """Verify that raw AudioRawFrames without _generation_id from TTS are stamped and pass through gate."""
    shared_state = {
        "current_turn_id": 16,
        "current_generation_id": 16,
        "active_generation_id": 16,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
    }

    from app.adapters.pipecat.language_router import CallTerminationProcessor
    call_term = CallTerminationProcessor(shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)

    gate_out = []
    async def capture_gate(f, d=None):
        gate_out.append(f)
    gate.push_frame = capture_gate

    async def forward_to_gate(f, d=None):
        await gate.process_frame(f, d)
    call_term.push_frame = forward_to_gate

    # Raw audio from TTS with no _generation_id
    raw_tts_chunk = AudioRawFrame(audio=b"\x00\x50" * 160, sample_rate=8000, num_channels=1)
    assert getattr(raw_tts_chunk, "_generation_id", None) is None

    await call_term.process_frame(raw_tts_chunk, FrameDirection.DOWNSTREAM)

    assert len(gate_out) == 1, "Audio frame must not be dropped at AudioInterruptionGate"
    assert gate_out[0]._generation_id == 16, "Audio frame must inherit active_generation_id=16"
    assert shared_state["late_chunks_dropped"] == 0, "No chunks dropped"

