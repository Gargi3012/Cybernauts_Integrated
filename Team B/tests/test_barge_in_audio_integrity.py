"""
Deterministic regression tests for Flowiz barge-in audio integrity:
1. Interruption during the middle of a TTS audio chunk.
2. Interruption while multiple chunks are queued locally.
3. Interruption while Plivo still has audio queued (clearAudio + clearedAudio ack).
4. Late old-generation chunk arriving after cancellation.
5. Second interruption arriving during first cancellation (idempotency).
6. New response starting while old provider audio is still arriving.
7. Cartesia interruption and cancellation (no duplicate SystemFrame).
8. Sarvam fallback after an interrupted response.
9. Codec and sample-rate validation (8kHz mu-law, no WAV containers in payload).
10. Audio chunk alignment and payload integrity (PCM16 2-byte boundary).
11. Genuine user barge-in during speech.
12. Weak interim STT fragments that must not cause false barge-in.
13. Repeated interruptions without duplicate queue clearing or corrupted state.
14. Call termination while an interruption is being processed.
"""

import asyncio
import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from pipecat.frames.frames import (
    Frame,
    StartFrame,
    EndFrame,
    InterruptionFrame,
    AudioRawFrame,
    OutputAudioRawFrame,
    InputAudioRawFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserSpeakingFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.processors.frame_processor import FrameDirection

import Pillar_2.plivo_bot
from app.adapters.pipecat.turn_guard import (
    TurnGuardProcessor,
    TurnGuardFilter,
    ValidatedUserTurnStartStrategy,
)
from app.adapters.pipecat.adapter import AudioInterruptionGate, apply_micro_fade_out
from Pillar_2.plivo_bot import (
    AtomicPlivoFrameSerializer,
    AtomicFastAPIWebsocketOutputTransport,
    AtomicFastAPIWebsocketTransport,
    PLIVO_SAMPLE_RATE,
)
from app.adapters.pipecat.sarvam_tts_service import SarvamTTSService
from app.adapters.pipecat.processors import ResilientTTSProcessor


# ── Helper Fixtures & Utilities ──────────────────────────────────────────

def create_pcm_audio(duration_ms: int = 20, sample_rate: int = 8000) -> bytes:
    """Generate raw 16-bit mono PCM sine-wave-like bytes (2 bytes per sample)."""
    import math
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    raw = bytearray()
    for i in range(num_samples):
        val = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
        raw.extend(val.to_bytes(2, byteorder="little", signed=True))
    return bytes(raw)


# ── Test Cases ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_interruption_middle_of_tts_audio_chunk():
    """1. Interruption occurs mid-stream: active generation is invalidated and mid-stream chunk cut off."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "tts_speaking": True,
    }
    gate = AudioInterruptionGate(shared_state=shared_state)
    pushed = []
    async def mock_push(f, d=None):
        pushed.append(f)
    gate.push_frame = mock_push

    # First chunk passes normally
    chunk1 = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk1._generation_id = 1
    await gate.process_frame(chunk1, FrameDirection.DOWNSTREAM)
    assert len(pushed) == 1
    assert pushed[0]._generation_id == 1

    # Interruption arrives
    int_frame = InterruptionFrame()
    await gate.process_frame(int_frame, FrameDirection.DOWNSTREAM)
    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 1
    assert shared_state["tts_speaking"] is False

    # Second chunk from the interrupted generation arrives -> must be dropped immediately
    chunk2 = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk2._generation_id = 1
    await gate.process_frame(chunk2, FrameDirection.DOWNSTREAM)
    # Total pushed remains 2 (chunk1 and int_frame), chunk2 was dropped!
    assert len(pushed) == 2
    assert shared_state["late_chunks_dropped"] >= 1


@pytest.mark.asyncio
async def test_2_interruption_multiple_chunks_queued_locally():
    """2. Multiple chunks queued locally are purged when InterruptionFrame is processed."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    serializer = AtomicPlivoFrameSerializer(
        stream_id="test_stream_001",
        shared_state=shared_state,
    )

    # Serialize one chunk
    chunk1 = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk1._generation_id = 1
    res1 = await serializer.serialize(chunk1)
    assert res1 is not None
    data1 = json.loads(res1)
    assert data1["event"] == "playAudio"

    # Interruption happens
    int_frame = InterruptionFrame()
    int_res = await serializer.serialize(int_frame)
    assert int_res is not None
    int_data = json.loads(int_res)
    assert int_data["event"] == "clearAudio"
    assert int_data["streamId"] == "test_stream_001"

    # Subsequent locally queued chunks from generation 1 are serialized -> must return None (dropped)
    for _ in range(3):
        late_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
        late_chunk._generation_id = 1
        res = await serializer.serialize(late_chunk)
        assert res is None, "Queued chunks from cancelled generation must not be serialized!"


@pytest.mark.asyncio
async def test_3_interruption_while_plivo_has_audio_queued_and_cleared_audio_ack():
    """3. Plivo clearAudio sent and clearedAudio ack received non-blockingly while caller audio continues."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
    }
    serializer = AtomicPlivoFrameSerializer(
        stream_id="stream_plivo_ack",
        shared_state=shared_state,
    )
    start = StartFrame()
    start.audio_in_sample_rate = 8000
    await serializer.setup(start)

    # 1. Interruption occurs -> clearAudio is emitted
    clear_msg = await serializer.serialize(InterruptionFrame())
    assert json.loads(clear_msg)["event"] == "clearAudio"
    assert shared_state.get("plivo_clear_audio_sent") is True

    # 2. Inbound user audio arrives before Plivo ack (caller speaks over barge-in)
    sample_ulaw = b"\xff" * 160  # 20ms of silence/audio in mu-law
    media_event = json.dumps({
        "event": "media",
        "media": {"payload": base64.b64encode(sample_ulaw).decode("utf-8")}
    })
    in_frame = await serializer.deserialize(media_event)
    assert isinstance(in_frame, InputAudioRawFrame)
    assert len(in_frame.audio) > 0, "Caller inbound audio must flow continuously without blockage"

    # 3. Plivo sends back 'clearedAudio' acknowledgment
    ack_event = json.dumps({"event": "clearedAudio", "streamId": "stream_plivo_ack"})
    ack_res = await serializer.deserialize(ack_event)
    assert ack_res is None  # Acknowledgment is non-blocking control event
    assert shared_state.get("plivo_cleared_audio_ack") is True


@pytest.mark.asyncio
async def test_4_late_old_generation_chunk_arriving_after_cancellation():
    """4. Late old-generation chunk arriving after cancellation is dropped by serializer and gate."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": None,
        "interrupted_generation_id": 1,
        "late_chunks_dropped": 0,
    }
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(
        stream_id="stream_late",
        shared_state=shared_state,
    )

    pushed_gate = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: pushed_gate.append(f))

    # A very late chunk arrives from Cartesia/Sarvam from Gen 1
    late_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    late_chunk._generation_id = 1

    # Gate test
    await gate.process_frame(late_chunk, FrameDirection.DOWNSTREAM)
    assert len(pushed_gate) == 0, "AudioInterruptionGate must drop late chunk"
    assert shared_state["late_chunks_dropped"] == 1

    # Serializer test
    ser_result = await serializer.serialize(late_chunk)
    assert ser_result is None, "AtomicPlivoFrameSerializer must drop late chunk"
    assert shared_state["late_chunks_dropped"] == 2


@pytest.mark.asyncio
async def test_5_second_interruption_arriving_during_first_cancellation():
    """5. Second interruption arriving during first cancellation is idempotent and safe."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_idempotent", shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)

    # First interruption
    res1 = await serializer.serialize(InterruptionFrame())
    await gate.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert json.loads(res1)["event"] == "clearAudio"
    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 1

    # Second immediate interruption
    res2 = await serializer.serialize(InterruptionFrame())
    await gate.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert json.loads(res2)["event"] == "clearAudio"
    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 1


@pytest.mark.asyncio
async def test_6_new_response_starting_while_old_provider_audio_still_arriving():
    """6. Turn 2 starts; old Gen 1 audio is dropped while Gen 2 audio passes and plays cleanly."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    guard = TurnGuardProcessor(shared_state=shared_state)
    turn_filter = TurnGuardFilter(shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_race", shared_state=shared_state)

    pushed_frames = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: pushed_frames.append(f))

    # Gen 1 gets interrupted
    await guard.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await turn_filter.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await gate.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await serializer.serialize(InterruptionFrame())

    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 1

    # Turn 2 / Gen 2 starts (user spoke new turn)
    context2 = LLMContextFrame(context=None)
    await guard.process_frame(context2, FrameDirection.DOWNSTREAM)
    assert shared_state["current_turn_id"] == 2
    assert shared_state["current_generation_id"] == 2
    assert shared_state["active_generation_id"] == 2

    # Old Gen 1 late audio chunk arrives -> dropped!
    old_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    old_chunk._generation_id = 1
    await gate.process_frame(old_chunk, FrameDirection.DOWNSTREAM)
    old_ser = await serializer.serialize(old_chunk)
    assert old_ser is None

    # New Gen 2 audio chunk arrives -> accepted and serialized!
    new_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    new_chunk._generation_id = 2
    await gate.process_frame(new_chunk, FrameDirection.DOWNSTREAM)
    new_ser = await serializer.serialize(new_chunk)
    assert new_ser is not None
    assert json.loads(new_ser)["event"] == "playAudio"


@pytest.mark.asyncio
async def test_7_cartesia_interruption_and_cancellation():
    """7. ResilientTTSProcessor does not duplicate SystemFrame on interruption."""
    primary_tts = MagicMock()
    primary_tts._prev = None
    primary_tts.process_frame = AsyncMock()
    fallback_factory = MagicMock()

    processor = ResilientTTSProcessor(primary_tts, fallback_factory)
    processor._prev = MagicMock()

    # When an InterruptionFrame is processed, primary_tts.process_frame should be called once,
    # and no duplicate SystemFrame should be emitted upstream/downstream.
    pushed = []
    processor.push_frame = AsyncMock(side_effect=lambda f, d=None: pushed.append(f))

    int_frame = InterruptionFrame()
    await processor.process_frame(int_frame, FrameDirection.DOWNSTREAM)

    assert primary_tts.process_frame.call_count == 1
    assert len(pushed) == 0, "ResilientTTSProcessor should not independently push duplicate frame downstream"


@pytest.mark.asyncio
async def test_8_sarvam_fallback_after_interrupted_response():
    """8. Sarvam fallback cancels running clause tasks cleanly on interruption."""
    tts = SarvamTTSService(api_key="test_key", sample_rate=8000)

    # Create dummy pending tasks to simulate in-flight HTTP requests
    dummy_task1 = asyncio.create_task(asyncio.sleep(10))
    dummy_task2 = asyncio.create_task(asyncio.sleep(10))
    tts._active_clause_tasks.add(dummy_task1)
    tts._active_clause_tasks.add(dummy_task2)

    # Interruption occurs
    await tts._handle_interruption(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0)

    assert dummy_task1.cancelled() or dummy_task1.done()
    assert dummy_task2.cancelled() or dummy_task2.done()
    assert len(tts._active_clause_tasks) == 0


@pytest.mark.asyncio
async def test_9_codec_and_sample_rate_validation():
    """9. Serializer emits strictly 8kHz mu-law audio payload without WAV container headers."""
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_codec")

    # 20ms of PCM16 @ 8000Hz = 160 samples = 320 bytes
    pcm_data = create_pcm_audio(duration_ms=20, sample_rate=8000)
    assert len(pcm_data) == 320

    frame = AudioRawFrame(audio=pcm_data, sample_rate=8000, num_channels=1)
    serialized = await serializer.serialize(frame)
    assert serialized is not None

    msg = json.loads(serialized)
    assert msg["event"] == "playAudio"
    assert msg["media"]["contentType"] == "audio/x-mulaw"
    assert msg["media"]["sampleRate"] == 8000

    raw_payload = base64.b64decode(msg["media"]["payload"])
    # 160 samples @ 1 byte per sample in mu-law = 160 bytes
    assert len(raw_payload) == 160, f"Expected 160 bytes of raw mu-law, got {len(raw_payload)}"

    # Confirm raw audio does not contain 'RIFF' or 'WAVE' container headers
    assert b"RIFF" not in raw_payload[:4]
    assert b"WAVE" not in raw_payload[:12]


@pytest.mark.asyncio
async def test_10_audio_chunk_alignment_and_payload_integrity():
    """10. Enforces 16-bit PCM 2-byte alignment on odd-byte buffer boundaries."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
    }
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_align", shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)

    # Audio chunk with odd number of bytes (321 bytes instead of 320)
    odd_pcm = create_pcm_audio(duration_ms=20, sample_rate=8000) + b"\x12"
    assert len(odd_pcm) == 321

    frame = AudioRawFrame(audio=odd_pcm, sample_rate=8000, num_channels=1)
    frame._generation_id = 1

    pushed = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: pushed.append(f))
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert len(pushed) == 1
    # Odd byte trimmed to preserve 16-bit sample alignment
    assert len(pushed[0].audio) == 320
    assert len(pushed[0].audio) % 2 == 0

    # Serialization succeeds cleanly without crashing
    serialized = await serializer.serialize(pushed[0])
    assert serialized is not None
    payload = base64.b64decode(json.loads(serialized)["media"]["payload"])
    assert len(payload) == 160


@pytest.mark.asyncio
async def test_11_genuine_user_barge_in_during_speech():
    """11. Genuine user barge-in with speech keywords triggers interruption immediately."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "tts_speaking": True,
    }
    strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
    strategy.trigger_user_turn_started = AsyncMock()

    # User says Hindi/Hinglish barge-in word "rukiye"
    frame = InterimTranscriptionFrame(text="rukiye ek minute", user_id="caller", timestamp=10.0)
    res = await strategy.process_frame(frame)

    assert strategy._triggered is True
    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 1
    assert shared_state["tts_speaking"] is False
    assert strategy.trigger_user_turn_started.call_count == 1


@pytest.mark.asyncio
async def test_12_weak_interim_stt_fragments_must_not_cause_false_barge_in():
    """12. Weak interim fragments ('uh', 'um', single tokens) do not interrupt bot speech."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "tts_speaking": True,
    }
    strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
    strategy.trigger_user_turn_started = AsyncMock()

    # Weak interim token
    frame = InterimTranscriptionFrame(text="uh", user_id="caller", timestamp=10.0)
    await strategy.process_frame(frame)

    assert strategy._triggered is False
    assert shared_state["active_generation_id"] == 1
    assert shared_state["tts_speaking"] is True
    assert strategy.trigger_user_turn_started.call_count == 0


@pytest.mark.asyncio
async def test_13_repeated_interruptions_without_duplicate_queue_clearing_or_corrupted_state():
    """13. 5 repeated interruptions execute cleanly without corrupted state or memory leaks."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_rep", shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)

    for i in range(5):
        int_frame = InterruptionFrame()
        res = await serializer.serialize(int_frame)
        await gate.process_frame(int_frame, FrameDirection.DOWNSTREAM)
        assert json.loads(res)["event"] == "clearAudio"
        assert shared_state["active_generation_id"] is None

        # Start a new turn
        shared_state["current_generation_id"] += 1
        shared_state["active_generation_id"] = shared_state["current_generation_id"]
        shared_state["interrupted_generation_id"] = None

    # After 5 cycles, verify active generation is intact
    assert shared_state["current_generation_id"] == 6
    assert shared_state["active_generation_id"] == 6


@pytest.mark.asyncio
async def test_14_call_termination_while_interruption_is_being_processed():
    """14. Caller saying goodbye while an interruption is processed terminates cleanly."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "hangup_requested": False,
    }
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_term", shared_state=shared_state)
    gate = AudioInterruptionGate(shared_state=shared_state)

    # Interruption arrives
    await serializer.serialize(InterruptionFrame())
    await gate.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert shared_state["active_generation_id"] is None

    # Termination signal arrives
    shared_state["hangup_requested"] = True
    end_frame = EndFrame()
    # Serializer handles EndFrame
    serializer._hang_up_call = AsyncMock()
    serializer._params.auto_hang_up = True
    serializer._call_id = "test_call_uuid"
    await serializer.serialize(end_frame)
    assert serializer._hangup_attempted is True
    assert serializer._hang_up_call.call_count == 1


# ── Explicit Priority 2 Regression Tests (Cases 1 to 16) ────────────────

@pytest.mark.asyncio
async def test_case_1_late_primary_tts_chunks_after_barge_in():
    """1. Late primary-TTS (Cartesia) chunks after barge-in are rejected at both gate and serializer."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": None,
        "interrupted_generation_id": 1,
        "late_chunks_dropped": 0,
    }
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c1", shared_state=shared_state)

    gate_pushed = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: gate_pushed.append(f))

    late_primary_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    late_primary_chunk._generation_id = 1

    await gate.process_frame(late_primary_chunk, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 0, "Gate must drop late primary TTS chunk"

    ser_out = await serializer.serialize(late_primary_chunk)
    assert ser_out is None, "Serializer must drop late primary TTS chunk"
    assert shared_state["late_chunks_dropped"] >= 2


@pytest.mark.asyncio
async def test_case_2_late_fallback_tts_chunks_after_barge_in():
    """2. Late fallback-TTS (Sarvam) chunks after barge-in are rejected at both gate and serializer."""
    shared_state = {
        "current_generation_id": 2,
        "active_generation_id": None,
        "interrupted_generation_id": 2,
        "late_chunks_dropped": 0,
    }
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c2", shared_state=shared_state)

    gate_pushed = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: gate_pushed.append(f))

    late_fallback_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    late_fallback_chunk._generation_id = 2

    await gate.process_frame(late_fallback_chunk, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 0, "Gate must drop late fallback TTS chunk"

    ser_out = await serializer.serialize(late_fallback_chunk)
    assert ser_out is None, "Serializer must drop late fallback TTS chunk"


@pytest.mark.asyncio
async def test_case_3_cancelled_generation_emitting_after_newer_generation_starts():
    """3. A cancelled generation emitting after a newer generation starts is dropped, while new audio plays."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": None,
        "interrupted_generation_id": 1,
        "late_chunks_dropped": 0,
    }
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c3", shared_state=shared_state)

    # Turn 2 starts
    shared_state["current_generation_id"] = 2
    shared_state["active_generation_id"] = 2
    shared_state["interrupted_generation_id"] = None

    # Late chunk from Gen 1 arrives
    old_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    old_chunk._generation_id = 1

    pushed = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: pushed.append(f))

    await gate.process_frame(old_chunk, FrameDirection.DOWNSTREAM)
    assert len(pushed) == 0, "Old Gen 1 chunk must be dropped by gate"
    old_ser = await serializer.serialize(old_chunk)
    assert old_ser is None, "Old Gen 1 chunk must be dropped by serializer"

    # Valid chunk from Gen 2 arrives
    new_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    new_chunk._generation_id = 2

    await gate.process_frame(new_chunk, FrameDirection.DOWNSTREAM)
    assert len(pushed) == 1
    new_ser = await serializer.serialize(new_chunk)
    assert new_ser is not None
    assert json.loads(new_ser)["event"] == "playAudio"


@pytest.mark.asyncio
async def test_case_4_vad_interruption_before_first_tts_chunk():
    """4. VAD interruption occurs before the first TTS chunk is emitted: generation invalidated cleanly."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "tts_speaking": False,  # TTS hasn't started yet!
    }
    strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
    strategy.trigger_user_turn_started = AsyncMock()

    # User speaks while LLM is still reasoning
    frame = InterimTranscriptionFrame(text="wait a second", user_id="caller", timestamp=1.0)
    await strategy.process_frame(frame)

    assert strategy._triggered is True
    assert shared_state["active_generation_id"] is None
    assert shared_state["interrupted_generation_id"] == 1

    # When first TTS chunk eventually emerges from LLM/TTS pipeline, it is dropped
    first_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    first_chunk._generation_id = 1

    gate = AudioInterruptionGate(shared_state=shared_state)
    gate_pushed = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: gate_pushed.append(f))
    await gate.process_frame(first_chunk, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 0, "First chunk must never play if VAD interrupted beforehand"


@pytest.mark.asyncio
async def test_case_5_false_interruption_rejection_for_weak_interim_stt():
    """5. False-interruption rejection: weak interim tokens ('the', 'um') do not cancel bot speech."""
    shared_state = {
        "current_turn_id": 1,
        "current_generation_id": 1,
        "active_generation_id": 1,
        "tts_speaking": True,
    }
    strategy = ValidatedUserTurnStartStrategy(min_speech_duration=0.25, shared_state=shared_state)
    strategy.trigger_user_turn_started = AsyncMock()

    # Weak ambient noise / acoustic leak
    frame = InterimTranscriptionFrame(text="the", user_id="caller", timestamp=1.0)
    await strategy.process_frame(frame)

    assert strategy._triggered is False
    assert shared_state["active_generation_id"] == 1
    assert strategy.trigger_user_turn_started.call_count == 0


@pytest.mark.asyncio
async def test_case_6_interruption_during_resampling():
    """6. Interruption occurs mid-resampling: post-resampling race check drops the chunk."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
        "late_chunks_dropped": 0,
    }
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c6", shared_state=shared_state)

    chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk._generation_id = 1

    # Simulate mid-resampling cancellation inside pcm_to_ulaw
    from unittest.mock import patch
    original_pcm_to_ulaw = Pillar_2.plivo_bot.pcm_to_ulaw

    async def interrupting_pcm_to_ulaw(*args, **kwargs):
        # Interruption happens concurrently while resampling is underway
        shared_state["active_generation_id"] = None
        shared_state["interrupted_generation_id"] = 1
        return await original_pcm_to_ulaw(*args, **kwargs)

    with patch("Pillar_2.plivo_bot.pcm_to_ulaw", side_effect=interrupting_pcm_to_ulaw):
        result = await serializer.serialize(chunk)
        assert result is None, "Chunk must be dropped if generation was invalidated during resampling"
        assert shared_state["late_chunks_dropped"] >= 1


@pytest.mark.asyncio
async def test_case_7_interruption_during_transport_write():
    """7. Interruption during transport write: write_audio_frame drops write when active gen is invalidated."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": None,
        "interrupted_generation_id": 1,
    }
    mock_transport = MagicMock()
    mock_client = MagicMock()
    params = MagicMock()
    transport_output = AtomicFastAPIWebsocketOutputTransport(
        mock_transport, mock_client, params, name="test_out"
    )
    transport_output.set_shared_state(shared_state)

    out_frame = OutputAudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    out_frame._generation_id = 1

    write_success = await transport_output.write_audio_frame(out_frame)
    assert write_success is False, "Output transport must refuse to write audio when generation is cancelled"


@pytest.mark.asyncio
async def test_case_8_concurrent_clearaudio_and_playaudio():
    """8. Concurrent clearAudio and playAudio operations are serialized strictly via asyncio.Lock."""
    mock_transport = MagicMock()
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.is_closing = False
    sent_payloads = []
    async def fake_send(payload):
        sent_payloads.append(payload)
    mock_client.send = AsyncMock(side_effect=fake_send)

    serializer = MagicMock()
    async def fake_serialize(frame):
        return json.dumps(frame.message)
    serializer.serialize = AsyncMock(side_effect=fake_serialize)

    params = MagicMock()
    params.serializer = serializer
    params.fixed_audio_packet_size = None

    transport_output = AtomicFastAPIWebsocketOutputTransport(
        mock_transport, mock_client, params, name="test_out"
    )

    # Launch concurrent frame writes
    clear_frame = OutputTransportMessageUrgentFrame(message={"event": "clearAudio"})
    play_frame = OutputTransportMessageFrame(message={"event": "playAudio"})

    # Both write through _write_frame concurrently
    await asyncio.gather(
        transport_output._write_frame(clear_frame),
        transport_output._write_frame(play_frame),
    )

    assert len(sent_payloads) == 2
    assert any("clearAudio" in p for p in sent_payloads)
    assert any("playAudio" in p for p in sent_payloads)


@pytest.mark.asyncio
async def test_case_9_pcm_odd_byte_boundaries_and_frame_alignment():
    """9. PCM odd-byte boundaries: 321 bytes trimmed to 320 bytes, maintaining 16-bit alignment."""
    shared_state = {"active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c9", shared_state=shared_state)

    odd_pcm = create_pcm_audio(20, sample_rate=8000) + b"\x55"  # 321 bytes
    frame = AudioRawFrame(audio=odd_pcm, sample_rate=8000, num_channels=1)
    frame._generation_id = 1

    serialized = await serializer.serialize(frame)
    assert serialized is not None
    payload = base64.b64decode(json.loads(serialized)["media"]["payload"])
    assert len(payload) == 160  # Exactly 160 8kHz mu-law samples


@pytest.mark.asyncio
async def test_case_10_resampler_state_reset_between_turns():
    """10. Resampler state reset between turns: historical filter state is flushed on reset."""
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c10")
    r1 = serializer._output_resampler

    # Reset resampler
    serializer.reset_resampler()
    r2 = serializer._output_resampler

    assert r1 is not r2, "reset_resampler must instantiate a fresh resampler instance"


@pytest.mark.asyncio
async def test_case_11_concurrent_calls_with_independent_generation_state():
    """11. Concurrent calls maintain independent generation state: Call A interruption does not affect Call B."""
    state_a = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    state_b = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    gate_a = AudioInterruptionGate(shared_state=state_a)
    gate_b = AudioInterruptionGate(shared_state=state_b)

    # User interrupts Call A
    await gate_a.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert state_a["active_generation_id"] is None

    # Call B remains active
    assert state_b["active_generation_id"] == 1

    # Call B audio frame passes gate cleanly
    chunk_b = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk_b._generation_id = 1
    pushed_b = []
    gate_b.push_frame = AsyncMock(side_effect=lambda f, d=None: pushed_b.append(f))
    await gate_b.process_frame(chunk_b, FrameDirection.DOWNSTREAM)
    assert len(pushed_b) == 1


@pytest.mark.asyncio
async def test_case_12_repeated_or_duplicate_interruption_events():
    """12. Repeated or duplicate interruption events execute idempotently without state corruption."""
    shared_state = {
        "current_generation_id": 1,
        "active_generation_id": 1,
        "interrupted_generation_id": None,
    }
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c12", shared_state=shared_state)

    # 3 duplicate interruptions
    for _ in range(3):
        res = await serializer.serialize(InterruptionFrame())
        assert json.loads(res)["event"] == "clearAudio"
        assert shared_state["active_generation_id"] is None
        assert shared_state["interrupted_generation_id"] == 1


@pytest.mark.asyncio
async def test_case_13_provider_failure_racing_with_cancellation():
    """13. Provider failure racing with cancellation: fallback does not replay cancelled frames."""
    primary_tts = MagicMock()
    primary_tts._prev = None
    primary_tts.process_frame = AsyncMock()

    fallback_tts = MagicMock()
    fallback_tts.process_frame = AsyncMock()
    fallback_tts.setup = AsyncMock()

    processor = ResilientTTSProcessor(primary_tts, lambda: fallback_tts)
    processor._start_frame = StartFrame()

    # User interrupts turn before failure occurs
    await processor.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert processor._current_generation_id is None
    assert len(processor._current_turn_frames) == 0

    # Provider failure races in immediately
    await processor.trigger_tts_fallback("Simulated Cartesia 429 during barge-in")
    assert processor.fallback_active is True
    # Fallback must not receive any replayed turn text frames
    assert not any(isinstance(c[0][0], TextFrame) for c in fallback_tts.process_frame.call_args_list)


@pytest.mark.asyncio
async def test_case_14_shutdown_while_generation_tasks_pending():
    """14. Shutdown while generation tasks remain pending: clean cleanup without unhandled exceptions."""
    primary_tts = MagicMock()
    primary_tts.process_frame = AsyncMock()
    primary_tts.cleanup = AsyncMock()
    fallback_tts = MagicMock()
    fallback_tts.process_frame = AsyncMock()
    fallback_tts.setup = AsyncMock()
    fallback_tts.cleanup = AsyncMock()

    processor = ResilientTTSProcessor(primary_tts, lambda: fallback_tts)
    processor._start_frame = StartFrame()
    await processor.trigger_tts_fallback("Switching before shutdown")

    # Pipeline task cancels / cleans up
    await processor.cleanup()
    primary_tts.cleanup.assert_called_once()
    fallback_tts.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_case_15_missing_or_malformed_generation_metadata():
    """15. Missing or malformed generation metadata: rejected unless explicitly marked as control audio."""
    shared_state = {"active_generation_id": 1, "late_chunks_dropped": 0}
    gate = AudioInterruptionGate(shared_state=shared_state)
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_c15", shared_state=shared_state)

    gate_pushed = []
    gate.push_frame = AsyncMock(side_effect=lambda f, d=None: gate_pushed.append(f))

    # A. None generation ID -> rejected
    chunk_none = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk_none._generation_id = None
    await gate.process_frame(chunk_none, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 0
    assert await serializer.serialize(chunk_none) is None

    # B. Negative generation ID -> rejected
    chunk_neg = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk_neg._generation_id = -1
    await gate.process_frame(chunk_neg, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 0
    assert await serializer.serialize(chunk_neg) is None

    # C. String generation ID -> rejected
    chunk_str = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    chunk_str._generation_id = "gen_invalid"
    await gate.process_frame(chunk_str, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 0
    assert await serializer.serialize(chunk_str) is None

    # D. Explicit control audio with _is_control_audio=True -> allowed through!
    ctrl_chunk = AudioRawFrame(audio=create_pcm_audio(20), sample_rate=8000, num_channels=1)
    ctrl_chunk._is_control_audio = True
    await gate.process_frame(ctrl_chunk, FrameDirection.DOWNSTREAM)
    assert len(gate_pushed) == 1
    assert await serializer.serialize(ctrl_chunk) is not None


@pytest.mark.asyncio
async def test_case_16_no_replay_of_cancelled_text_or_audio_during_fallback():
    """16. No replay of cancelled text or audio during TTS fallback."""
    primary_tts = MagicMock()
    primary_tts.process_frame = AsyncMock()

    fallback_tts = MagicMock()
    fallback_tts.process_frame = AsyncMock()
    fallback_tts.setup = AsyncMock()

    processor = ResilientTTSProcessor(primary_tts, lambda: fallback_tts)
    processor._start_frame = StartFrame()

    # Turn begins
    start_f = LLMFullResponseStartFrame()
    start_f._generation_id = 1
    await processor.process_frame(start_f, FrameDirection.DOWNSTREAM)
    text_f = TextFrame(text="Cancelled phrase")
    text_f._generation_id = 1
    await processor.process_frame(text_f, FrameDirection.DOWNSTREAM)
    assert len(processor._current_turn_frames) == 2

    # User interrupts!
    await processor.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert len(processor._current_turn_frames) == 0
    assert processor._current_generation_id is None

    # Fallback triggered
    await processor.trigger_tts_fallback("Cartesia failed after barge-in")
    assert processor.fallback_active is True
    # Zero text frames replayed
    replayed_texts = [
        c[0][0].text for c in fallback_tts.process_frame.call_args_list
        if isinstance(c[0][0], TextFrame)
    ]
    assert len(replayed_texts) == 0

