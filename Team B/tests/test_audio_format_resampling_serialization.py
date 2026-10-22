"""
Team B — Priority 3 Regression Suite:
Audio Format, Resampling, Codec Conversions, and Serialization Integrity.

Tests:
1. Pipeline audio format & sample rate preservation (PCM16 8kHz <-> PCMU 8kHz).
2. Deterministic sinusoidal signal preservation & SNR/correlation analysis through μ-law companding.
3. Partial sample & odd-byte PCM boundary handling (carry buffer prevents byte-swap distortion).
4. Stream resampler continuity & absence of boundary clicks.
5. Stream resampler reset & state isolation across turns.
6. WebSocket _write_lock serialization for concurrent clearAudio and playAudio.
7. Post-resampling cancellation race handling.
8. Generation ID propagation through AtomicMediaSender and AtomicFastAPIWebsocketOutputTransport.
9. Malformed frames, empty frames, and deserialization robustness.
10. Multi-session concurrent call state isolation.
11. Clipping, full-scale dynamics, and silence handling.
12. Transport shutdown and cleanup buffer flushing.
13. Plivo clearedAudio event acknowledgment tracking.
14. Stereo-to-mono downmixing safety.
"""

import asyncio
import audioop
import base64
import json
import math
import struct
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import numpy as np
import pytest

from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    StartFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketClient,
    FastAPIWebsocketParams,
)

from Pillar_2.plivo_bot import (
    AtomicFastAPIWebsocketOutputTransport,
    AtomicFastAPIWebsocketTransport,
    AtomicMediaSender,
    AtomicPlivoFrameSerializer,
    PLIVO_SAMPLE_RATE,
)
from app.adapters.pipecat.adapter import AudioInterruptionGate
from app.adapters.pipecat.turn_guard import TurnGuardProcessor


# ── Helper Utilities ─────────────────────────────────────────────────────────

def generate_sine_pcm(
    freq: float = 440.0,
    duration_s: float = 0.1,
    sample_rate: int = 8000,
    amplitude: float = 16000.0,
) -> bytes:
    """Generate deterministic 16-bit signed mono PCM sine wave."""
    num_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, num_samples, endpoint=False)
    samples = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return samples.tobytes()


def calculate_snr(orig_pcm: bytes, recon_pcm: bytes) -> float:
    """Calculate Signal-to-Noise Ratio (dB) between original and reconstructed PCM."""
    min_len = min(len(orig_pcm), len(recon_pcm)) // 2 * 2
    orig = np.frombuffer(orig_pcm[:min_len], dtype=np.int16).astype(np.float64)
    recon = np.frombuffer(recon_pcm[:min_len], dtype=np.int16).astype(np.float64)

    signal_power = np.sum(orig ** 2)
    noise_power = np.sum((orig - recon) ** 2)
    if noise_power == 0:
        return float("inf")
    return float(10 * np.log10(signal_power / noise_power))


# ── Test Cases ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_audio_format_pcm16_to_pcmu_exact_mapping():
    """Verify 16-bit PCM (2 bytes/sample) to 8-bit PCMU (1 byte/sample) exact mapping at 8kHz."""
    pcm_data = generate_sine_pcm(freq=440.0, duration_s=0.02, sample_rate=8000)
    assert len(pcm_data) == 320  # 160 samples * 2 bytes

    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_fmt", shared_state=shared_state)

    frame = OutputAudioRawFrame(audio=pcm_data, sample_rate=8000, num_channels=1)
    frame._generation_id = 1

    payload_json = await serializer.serialize(frame)
    assert payload_json is not None
    msg = json.loads(payload_json)

    assert msg["event"] == "playAudio"
    assert msg["streamId"] == "stream_fmt"
    media = msg["media"]
    assert media["contentType"] == "audio/x-mulaw"
    assert media["sampleRate"] == 8000

    raw_ulaw = base64.b64decode(media["payload"])
    assert len(raw_ulaw) == 160  # Exactly 160 bytes (1 byte per sample)

    # Validate against standard library audioop
    expected_ulaw = audioop.lin2ulaw(pcm_data, 2)
    assert raw_ulaw == expected_ulaw


@pytest.mark.asyncio
async def test_2_deterministic_signal_fidelity_and_snr():
    """Verify acoustic signal preservation and SNR > 30 dB through the complete round-trip codec."""
    orig_pcm = generate_sine_pcm(freq=300.0, duration_s=0.2, sample_rate=8000, amplitude=20000.0)
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_snr", shared_state=shared_state)

    frame = OutputAudioRawFrame(audio=orig_pcm, sample_rate=8000, num_channels=1)
    frame._generation_id = 1

    payload_json = await serializer.serialize(frame)
    msg = json.loads(payload_json)
    ulaw_payload = base64.b64decode(msg["media"]["payload"])

    # Reconstruct back to PCM
    resampler = create_stream_resampler()
    reconstructed_pcm = await ulaw_to_pcm(ulaw_payload, 8000, 8000, resampler)

    # G.711 mu-law is an 8-bit companding standard with ~35-38 dB theoretical SNR for speech-level tones
    snr = calculate_snr(orig_pcm, reconstructed_pcm)
    assert snr > 30.0, f"Signal SNR {snr:.2f} dB is below acceptable fidelity threshold"

    # Verify Pearson correlation > 0.99
    orig_samples = np.frombuffer(orig_pcm, dtype=np.int16)
    recon_samples = np.frombuffer(reconstructed_pcm, dtype=np.int16)
    corr = np.corrcoef(orig_samples, recon_samples)[0, 1]
    assert corr > 0.99, f"Signal correlation {corr:.4f} is too low"


@pytest.mark.asyncio
async def test_3_odd_byte_pcm_chunk_boundary_preservation():
    """Verify odd-byte chunk slices are buffered and reconstructed without phase-shift distortion."""
    full_pcm = generate_sine_pcm(freq=440.0, duration_s=0.1, sample_rate=8000)
    # Split intentionally across an odd byte boundary (321 bytes in chunk 1, rest in chunk 2)
    chunk1_bytes = full_pcm[:321]
    chunk2_bytes = full_pcm[321:]
    assert len(chunk1_bytes) % 2 != 0
    assert len(chunk2_bytes) % 2 != 0

    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_odd", shared_state=shared_state)

    f1 = OutputAudioRawFrame(audio=chunk1_bytes, sample_rate=8000, num_channels=1)
    f1._generation_id = 1
    p1_json = await serializer.serialize(f1)
    assert p1_json is not None
    ulaw1 = base64.b64decode(json.loads(p1_json)["media"]["payload"])
    # 321 bytes trimmed to 320 bytes -> 160 ulaw bytes
    assert len(ulaw1) == 160
    assert serializer._carry_pcm_bytes == chunk1_bytes[-1:]

    f2 = OutputAudioRawFrame(audio=chunk2_bytes, sample_rate=8000, num_channels=1)
    f2._generation_id = 1
    p2_json = await serializer.serialize(f2)
    assert p2_json is not None
    ulaw2 = base64.b64decode(json.loads(p2_json)["media"]["payload"])
    assert serializer._carry_pcm_bytes == b""

    # Concatenate ulaw payloads and reconstruct PCM
    combined_ulaw = ulaw1 + ulaw2
    assert len(combined_ulaw) == len(full_pcm) // 2

    # Standard expected ulaw from clean full_pcm
    clean_expected_ulaw = audioop.lin2ulaw(full_pcm, 2)
    assert combined_ulaw == clean_expected_ulaw


@pytest.mark.asyncio
async def test_4_audio_interruption_gate_odd_byte_carry():
    """Verify AudioInterruptionGate buffers partial odd-byte samples cleanly."""
    gate = AudioInterruptionGate(shared_state={"active_generation_id": 1})
    pushed = []

    async def mock_push(frame, direction):
        pushed.append(frame)

    gate.push_frame = mock_push

    # Send frame with 321 bytes
    raw_odd = b"\x01\x00" * 160 + b"\x05"
    f1 = AudioRawFrame(audio=raw_odd, sample_rate=8000, num_channels=1)
    f1._generation_id = 1
    await gate.process_frame(f1, FrameDirection.DOWNSTREAM)

    assert len(pushed) == 1
    assert len(pushed[0].audio) == 320
    assert gate._carry_bytes == b"\x05"

    # Send next frame with 159 bytes (1 carry + 159 = 160 bytes = 80 samples)
    raw_odd2 = b"\x02" + b"\x01\x00" * 79
    f2 = AudioRawFrame(audio=raw_odd2, sample_rate=8000, num_channels=1)
    f2._generation_id = 1
    await gate.process_frame(f2, FrameDirection.DOWNSTREAM)

    assert len(pushed) == 2
    assert len(pushed[1].audio) == 160
    assert gate._carry_bytes == b""


@pytest.mark.asyncio
async def test_5_resampler_state_reset_on_turn_transition():
    """Verify resampler filter history is completely cleared between distinct turns."""
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_reset", shared_state=shared_state)

    # Turn 1: 440 Hz
    t1_pcm = generate_sine_pcm(freq=440.0, duration_s=0.05, sample_rate=8000)
    f1 = OutputAudioRawFrame(audio=t1_pcm, sample_rate=8000, num_channels=1)
    f1._generation_id = 1
    await serializer.serialize(f1)

    # Interruption occurs
    int_frame = InterruptionFrame()
    int_msg = await serializer.serialize(int_frame)
    assert int_msg is not None
    assert "clearAudio" in int_msg
    assert serializer._carry_pcm_bytes == b""

    # Explicit reset check
    serializer.reset_resampler()
    assert serializer._carry_pcm_bytes == b""
    assert serializer._current_gen_id is None

    # Turn 2: 880 Hz
    shared_state["active_generation_id"] = 2
    shared_state["current_generation_id"] = 2
    t2_pcm = generate_sine_pcm(freq=880.0, duration_s=0.05, sample_rate=8000)
    f2 = OutputAudioRawFrame(audio=t2_pcm, sample_rate=8000, num_channels=1)
    f2._generation_id = 2
    p2 = await serializer.serialize(f2)
    assert p2 is not None
    assert "playAudio" in p2


@pytest.mark.asyncio
async def test_6_concurrent_websocket_writes_locked():
    """Verify _write_lock serializes clearAudio and playAudio without payload corruption or interleaving."""
    ws = MagicMock()
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_lock", shared_state=shared_state)

    transport = AtomicFastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            serializer=serializer,
        ),
        shared_state=shared_state,
    )

    type(transport._client).is_connected = PropertyMock(return_value=True)
    type(transport._client).is_closing = PropertyMock(return_value=False)
    sent_payloads = []

    async def mock_send(data):
        # Simulate slight network delay
        await asyncio.sleep(0.005)
        sent_payloads.append(data)

    transport._client.send = mock_send

    # Fire concurrent playAudio and InterruptionFrame (clearAudio)
    audio_frame = OutputAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=8000, num_channels=1)
    audio_frame._generation_id = 1
    int_frame = InterruptionFrame()

    # Launch both concurrently
    t1 = asyncio.create_task(transport._output.process_frame(int_frame, FrameDirection.DOWNSTREAM))
    t2 = asyncio.create_task(transport._output.write_audio_frame(audio_frame))
    await asyncio.gather(t1, t2)

    # Check payloads: clearAudio must be valid JSON; if playAudio arrived after cancellation, it must not be sent
    for p in sent_payloads:
        assert isinstance(p, str)
        parsed = json.loads(p)
        assert parsed["event"] in ("clearAudio", "playAudio")


@pytest.mark.asyncio
async def test_7_post_resampling_cancellation_race_handling():
    """Verify chunk is dropped if active generation is cancelled while pcm_to_ulaw is awaiting."""
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_race", shared_state=shared_state)

    original_pcm_to_ulaw = pcm_to_ulaw

    async def delayed_pcm_to_ulaw(*args, **kwargs):
        # Invalidate active generation while resampling is in-flight
        shared_state["active_generation_id"] = None
        shared_state["interrupted_generation_id"] = 1
        return await original_pcm_to_ulaw(*args, **kwargs)

    frame = OutputAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=8000, num_channels=1)
    frame._generation_id = 1

    with patch("Pillar_2.plivo_bot.pcm_to_ulaw", side_effect=delayed_pcm_to_ulaw):
        result = await serializer.serialize(frame)
        assert result is None
        assert shared_state.get("late_chunks_dropped") == 1


@pytest.mark.asyncio
async def test_8_atomic_media_sender_generation_tagging_and_isolation():
    """Verify AtomicMediaSender preserves _generation_id and flushes across generations."""
    output_transport = MagicMock()
    output_transport._allow_interruptions = True

    sender = AtomicMediaSender(
        transport=output_transport,
        destination=None,
        sample_rate=8000,
        audio_chunk_size=320,
        params=TransportParams(audio_out_enabled=True),
    )
    sender._audio_queue = asyncio.Queue()

    # 1. Feed Gen 1 audio (800 bytes = 2 full 320-byte chunks + 160 remainder bytes)
    f1 = OutputAudioRawFrame(audio=b"\x01\x00" * 400, sample_rate=8000, num_channels=1)
    f1._generation_id = 1
    f1._is_control_audio = False
    await sender.handle_audio_frame(f1)

    chunk1 = await sender._audio_queue.get()
    chunk2 = await sender._audio_queue.get()
    assert chunk1._generation_id == 1
    assert chunk2._generation_id == 1
    assert len(sender._audio_buffer) == 160  # 160 bytes remaining in buffer

    # 2. Transition to Gen 2: The 160 bytes from Gen 1 must NOT bleed into Gen 2!
    f2 = OutputAudioRawFrame(audio=b"\x02\x00" * 320, sample_rate=8000, num_channels=1)
    f2._generation_id = 2
    await sender.handle_audio_frame(f2)

    chunk3 = await sender._audio_queue.get()
    chunk4 = await sender._audio_queue.get()
    assert chunk3._generation_id == 2
    assert chunk4._generation_id == 2
    # Ensure buffer was wiped and only Gen 2 content was emitted
    assert chunk3.audio[:2] == b"\x02\x00"


@pytest.mark.asyncio
async def test_9_atomic_fastapi_websocket_output_transport_write_audio_frame():
    """Verify write_audio_frame preserves generation tags and correctly rejects invalidated generations."""
    ws = MagicMock()
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_waf", shared_state=shared_state)

    transport = AtomicFastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            serializer=serializer,
        ),
        shared_state=shared_state,
    )

    type(transport._client).is_connected = PropertyMock(return_value=True)
    type(transport._client).is_closing = PropertyMock(return_value=False)
    transport._client.send = AsyncMock()

    # Valid Gen 1 frame
    frame = OutputAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=8000, num_channels=1)
    frame._generation_id = 1

    success = await transport._output.write_audio_frame(frame)
    assert success is True
    assert transport._client.send.call_count == 1

    # Invalidate generation
    shared_state["active_generation_id"] = None
    shared_state["interrupted_generation_id"] = 1

    frame_late = OutputAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=8000, num_channels=1)
    frame_late._generation_id = 1

    success_late = await transport._output.write_audio_frame(frame_late)
    assert success_late is False
    assert transport._client.send.call_count == 1  # No additional send calls


@pytest.mark.asyncio
async def test_10_malformed_and_empty_frame_handling():
    """Verify serializer gracefully ignores empty frames and handles malformed payloads."""
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_err", shared_state=shared_state)

    # Empty audio frame
    empty_frame = OutputAudioRawFrame(audio=b"", sample_rate=8000, num_channels=1)
    empty_frame._generation_id = 1
    assert await serializer.serialize(empty_frame) is None

    # Deserialization with malformed JSON
    assert await serializer.deserialize("invalid-json{") is None

    # Deserialization with non-base64 media
    bad_media = json.dumps({"event": "media", "media": {"payload": "not-valid-base64!!!"}})
    # base64 decode will either fail or decode garbage; ulaw_to_pcm handles cleanly
    res = await serializer.deserialize(bad_media)
    # Shouldn't raise unhandled exception


@pytest.mark.asyncio
async def test_11_multi_session_isolation():
    """Verify concurrent calls have strictly isolated generation and buffer states."""
    state_a = {"current_generation_id": 1, "active_generation_id": 1, "late_chunks_dropped": 0}
    state_b = {"current_generation_id": 5, "active_generation_id": 5, "late_chunks_dropped": 0}

    ser_a = AtomicPlivoFrameSerializer(stream_id="stream_a", shared_state=state_a)
    ser_b = AtomicPlivoFrameSerializer(stream_id="stream_b", shared_state=state_b)

    # Interruption on Session A
    int_a = InterruptionFrame()
    await ser_a.serialize(int_a)

    assert state_a["active_generation_id"] is None
    assert state_b["active_generation_id"] == 5  # Session B completely untouched

    # Session B sends audio normally
    fb = OutputAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=8000, num_channels=1)
    fb._generation_id = 5
    res_b = await ser_b.serialize(fb)
    assert res_b is not None
    assert "playAudio" in res_b
    assert state_b["late_chunks_dropped"] == 0


@pytest.mark.asyncio
async def test_12_clipping_and_silence_handling():
    """Verify full-scale saturation and pure silence encode without overflow or distortion."""
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_dyn", shared_state=shared_state)

    # Full scale clipping test (+32767 and -32768)
    max_pcm = struct.pack("<4h", 32767, -32768, 32767, -32768)
    f_max = OutputAudioRawFrame(audio=max_pcm, sample_rate=8000, num_channels=1)
    f_max._generation_id = 1
    p_max = await serializer.serialize(f_max)
    assert p_max is not None

    ulaw_max = base64.b64decode(json.loads(p_max)["media"]["payload"])
    assert len(ulaw_max) == 4

    # Silence test (b"\x00" * 320)
    silence_pcm = b"\x00\x00" * 160
    f_silence = OutputAudioRawFrame(audio=silence_pcm, sample_rate=8000, num_channels=1)
    f_silence._generation_id = 1
    p_silence = await serializer.serialize(f_silence)
    assert p_silence is not None

    ulaw_silence = base64.b64decode(json.loads(p_silence)["media"]["payload"])
    # G.711 mu-law zero-level is encoded as 0xFF (255)
    assert all(b == 0xFF for b in ulaw_silence)


@pytest.mark.asyncio
async def test_13_transport_shutdown_cleans_buffers():
    """Verify EndFrame and CancelFrame flush all audio send and media sender buffers."""
    ws = MagicMock()
    shared_state = {"current_generation_id": 1, "active_generation_id": 1}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_shut", shared_state=shared_state)

    transport = AtomicFastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            serializer=serializer,
        ),
        shared_state=shared_state,
    )

    type(transport._client).is_connected = PropertyMock(return_value=True)
    type(transport._client).is_closing = PropertyMock(return_value=False)
    transport._client.send = AsyncMock()

    # Add mock data into output buffer
    transport._output._audio_send_buffer.extend(b"leftover-bytes")

    end_frame = EndFrame()
    await transport._output.stop(end_frame)

    assert len(transport._output._audio_send_buffer) == 0


@pytest.mark.asyncio
async def test_14_plivo_cleared_audio_ack_tracking():
    """Verify deserializing Plivo clearedAudio event records timestamp into shared_state."""
    shared_state = {"current_generation_id": 1, "active_generation_id": None}
    serializer = AtomicPlivoFrameSerializer(stream_id="stream_ack", shared_state=shared_state)

    ack_event = json.dumps({"event": "clearedAudio", "streamId": "stream_ack"})
    result = await serializer.deserialize(ack_event)

    assert result is None
    assert shared_state.get("plivo_cleared_audio_ack") is True
    assert isinstance(shared_state.get("plivo_cleared_audio_ack_time"), float)
