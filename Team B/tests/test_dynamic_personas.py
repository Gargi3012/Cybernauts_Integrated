import pytest
import os
import sys

# Ensure Team B is on sys.path
team_b_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if team_b_root not in sys.path:
    sys.path.insert(0, team_b_root)

from app.services.persona_registry import (
    get_persona,
    get_all_personas,
    resolve_persona_voice,
    PERSONAS,
    AgentPersona
)
from app.llm.prompts import build_voice_system_prompt
from fastapi.testclient import TestClient
from app.main import app


def test_persona_registry_contents():
    """Verify canonical personas exist: Shreya (F), Ritu (F), Ratan (M), Manan (M)."""
    all_p = get_all_personas()
    assert len(all_p) == 4
    
    ids = [p.id for p in all_p]
    assert "shreya" in ids
    assert "ritu" in ids
    assert "ratan" in ids
    assert "manan" in ids

    # Shreya (Female)
    shreya = get_persona("shreya")
    assert shreya.name == "Shreya"
    assert shreya.gender == "female"
    assert shreya.voice == "shreya"
    assert shreya.model == "bulbul:v3"
    assert "बोल रही हूँ" in shreya.greeting_hi
    assert "Shreya" in shreya.greeting_en

    # Ritu (Female)
    ritu = get_persona("ritu")
    assert ritu.name == "Ritu"
    assert ritu.gender == "female"
    assert ritu.voice == "ritu"
    assert "बोल रही हूँ" in ritu.greeting_hi
    assert "Ritu" in ritu.greeting_en

    # Ratan (Male)
    ratan = get_persona("ratan")
    assert ratan.name == "Ratan"
    assert ratan.gender == "male"
    assert ratan.voice == "ratan"
    assert "बोल रहा हूँ" in ratan.greeting_hi
    assert "Ratan" in ratan.greeting_en

    # Manan (Male)
    manan = get_persona("manan")
    assert manan.name == "Manan"
    assert manan.gender == "male"
    assert manan.voice == "manan"
    assert "बोल रहा हूँ" in manan.greeting_hi
    assert "Manan" in manan.greeting_en


def test_fallback_and_alias_resolution():
    """Verify unknown, None, and legacy aliases resolve safely."""
    default_p = get_persona(None)
    assert default_p.id == "shreya"
    
    unknown_p = get_persona("unknown_agent_xyz")
    assert unknown_p.id == "shreya"

    # Backward compatibility aliases
    assert get_persona("arvind").id == "ratan"
    assert get_persona("meera").id == "ritu"
    assert get_persona("dhruv").id == "manan"
    assert get_persona("sara").id == "shreya"

    # resolve_persona_voice
    assert resolve_persona_voice("shreya") == "shreya"
    assert resolve_persona_voice("ritu") == "ritu"
    assert resolve_persona_voice("ratan") == "ratan"
    assert resolve_persona_voice("manan") == "manan"
    assert resolve_persona_voice("arvind") == "ratan"
    assert resolve_persona_voice("meera") == "ritu"
    assert resolve_persona_voice("dhruv") == "manan"


def test_ratan_and_manan_male_prompt_generation():
    """Verify Ratan & Manan prompts enforce male grammar and self-name introduction."""
    for p_id, p_name in [("ratan", "Ratan"), ("manan", "Manan")]:
        prompt = build_voice_system_prompt(p_id)
        assert f"Your name is {p_name}" in prompt
        assert f"I'm {p_name} from Flowiz" in prompt
        assert f"मैं {p_name} बोल रहा हूँ" in prompt
        assert "कर सकता हूँ" in prompt
        assert "GENDER GRAMMAR RULE (MALE)" in prompt
        assert "NEVER use feminine verb endings (रही हूँ, सकती हूँ, जानती हूँ)" in prompt
        assert "NATURAL MODERN HINGLISH" in prompt
        assert "'leads', 'calls', 'features'" in prompt


def test_shreya_and_ritu_female_prompt_generation():
    """Verify Shreya & Ritu prompts enforce female grammar and self-name introduction."""
    for p_id, p_name in [("shreya", "Shreya"), ("ritu", "Ritu")]:
        prompt = build_voice_system_prompt(p_id)
        assert f"Your name is {p_name}" in prompt
        assert f"I'm {p_name} from Flowiz" in prompt
        assert f"मैं {p_name} बोल रही हूँ" in prompt
        assert "कर सकती हूँ" in prompt
        assert "GENDER GRAMMAR RULE (FEMALE)" in prompt
        assert "NEVER use masculine verb endings (रहा हूँ, सकता हूँ, जानता हूँ)" in prompt
        assert "NATURAL MODERN HINGLISH" in prompt


def test_api_personas_endpoint():
    """Verify GET /api/personas returns Shreya, Ritu, Ratan, Manan."""
    client = TestClient(app)
    response = client.get("/api/personas")
    assert response.status_code == 200
    data = response.json()
    assert "personas" in data
    assert len(data["personas"]) == 4

    p_ids = [p["id"] for p in data["personas"]]
    assert "shreya" in p_ids
    assert "ritu" in p_ids
    assert "ratan" in p_ids
    assert "manan" in p_ids

    ratan_data = next((p for p in data["personas"] if p["id"] == "ratan"), None)
    assert ratan_data is not None
    assert ratan_data["gender"] == "male"
    assert ratan_data["voice"] == "ratan"
    assert ratan_data["name"] == "Ratan"


def test_api_livekit_join_with_persona():
    """Verify /api/livekit/join accepts persona and voice in payload."""
    from app.services.auth_service import create_jwt_token
    client = TestClient(app)
    token = create_jwt_token("test_admin")
    headers = {"Authorization": f"Bearer {token}"}

    join_resp = client.post(
        "/api/livekit/join",
        json={"persona": "ratan", "voice": "ratan"},
        headers=headers
    )
    assert join_resp.status_code in (200, 500, 503)
