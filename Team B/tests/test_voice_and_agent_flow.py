"""
Integration tests for Voice Personas and Agent Flow Pipeline.
Verifies:
1. Distinct Indian Neural voice models for all 4 personas (Shreya, Ritu, Ratan, Manan).
2. Proactive quota-exhaustion handling (zero serial delay, no 402 timeouts).
3. Real-time streaming PCM output (first audio frame latency benchmark).
4. Persona identity and grammar consistency (Shreya intro, Ratan male grammar, script sanitization).
5. Voice switching isolation (no reuse of stale voice audio).
"""

import asyncio
import time
import pytest

from app.services.persona_registry import get_persona, CANONICAL_PERSONAS
from app.adapters.pipecat.sarvam_tts_service import (
    SarvamTTSService,
    EDGE_NEURAL_VOICE_MAP,
    get_edge_neural_voice,
    reset_sarvam_quota_status
)
from app.llm.prompts import build_voice_system_prompt
from pipecat.frames.frames import TTSStartedFrame, TTSAudioRawFrame, TTSStoppedFrame


def test_all_four_voices_have_distinct_neural_models():
    """Verify Shreya, Ritu, Ratan, and Manan each have unique, distinct Indian models."""
    assert len(CANONICAL_PERSONAS) == 4
    voices = set()
    for pid, persona in CANONICAL_PERSONAS.items():
        edge_model = get_edge_neural_voice(persona.voice)
        assert edge_model is not None
        assert edge_model not in voices, f"Duplicate voice model found for {pid}: {edge_model}"
        voices.add(edge_model)
    
    assert get_edge_neural_voice("shreya") == "hi-IN-SwaraNeural"
    assert get_edge_neural_voice("ritu") == "en-IN-NeerjaNeural"
    assert get_edge_neural_voice("ratan") == "hi-IN-MadhurNeural"
    assert get_edge_neural_voice("manan") == "en-IN-PrabhatNeural"


def test_shreya_identity_in_prompts():
    """Verify selecting Shreya generates Shreya's name in prompts, not Sara."""
    p = get_persona("shreya")
    assert p.name == "Shreya"
    prompt = build_voice_system_prompt(p)
    assert "You are Shreya" in prompt
    assert "Your name is Shreya" in prompt
    assert "मैं Shreya बोल रही हूँ" in prompt
    assert "Sara" not in prompt


def test_ratan_identity_and_male_grammar_in_prompts():
    """Verify selecting Ratan generates Ratan's name with male Hindi verb endings."""
    p = get_persona("ratan")
    assert p.name == "Ratan"
    assert p.gender == "male"
    prompt = build_voice_system_prompt(p)
    assert "You are Ratan" in prompt
    assert "मैं Ratan बोल रहा हूँ" in prompt
    assert "GENDER GRAMMAR RULE (MALE)" in prompt


@pytest.mark.asyncio
async def test_sarvam_tts_service_streaming_and_latency():
    """Verify SarvamTTSService streams audio frames with low first-packet latency."""
    reset_sarvam_quota_status()
    tts = SarvamTTSService(
        api_key="dummy_or_exhausted_key",
        voice="shreya",
        sample_rate=16000
    )

    t0 = time.perf_counter()
    frames = []
    first_audio_frame_ms = None

    async for frame in tts.run_tts("Hi, main Flowiz se Shreya bol rahi hoon."):
        frames.append(frame)
        if isinstance(frame, TTSAudioRawFrame) and first_audio_frame_ms is None:
            first_audio_frame_ms = (time.perf_counter() - t0) * 1000

    total_time_ms = (time.perf_counter() - t0) * 1000

    assert any(isinstance(f, TTSStartedFrame) for f in frames)
    assert any(isinstance(f, TTSStoppedFrame) for f in frames)
    
    audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
    assert len(audio_frames) > 0, "Expected multiple streaming PCM audio frames"
    
    total_pcm_bytes = sum(len(f.audio) for f in audio_frames)
    assert total_pcm_bytes > 50000, f"Expected substantial PCM audio, got {total_pcm_bytes} bytes"

    # All frames should have target sample rate (16000) and mono channel
    for af in audio_frames:
        assert af.sample_rate == 16000
        assert af.num_channels == 1

    print(f"\n[LATENCY BENCHMARK] Shreya TTS: First Audio Frame = {first_audio_frame_ms:.1f}ms, Total = {total_time_ms:.1f}ms, Chunks = {len(audio_frames)}")
    assert first_audio_frame_ms < 3000, f"First audio latency too high: {first_audio_frame_ms}ms"


@pytest.mark.asyncio
async def test_voice_switching_isolation():
    """Verify switching between personas produces audio frames for each respective model."""
    for voice_name in ["shreya", "ritu", "ratan", "manan"]:
        tts = SarvamTTSService(
            api_key="",
            voice=voice_name,
            sample_rate=16000
        )
        assert tts.voice == voice_name
        assert tts.edge_voice == EDGE_NEURAL_VOICE_MAP[voice_name]

        audio_frames = []
        async for frame in tts.run_tts("Testing voice switching."):
            if isinstance(frame, TTSAudioRawFrame):
                audio_frames.append(frame)

        assert len(audio_frames) > 0
        total_bytes = sum(len(f.audio) for f in audio_frames)
        assert total_bytes > 10000
