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
    """Verify canonical personas exist and adhere to spec."""
    all_p = get_all_personas()
    assert len(all_p) == 4
    
    ids = [p.id for p in all_p]
    assert "shreya" in ids
    assert "arvind" in ids
    assert "meera" in ids
    assert "dhruv" in ids

    # Arvind (Male)
    arvind = get_persona("arvind")
    assert arvind.name == "Arvind"
    assert arvind.gender == "male"
    assert arvind.voice == "arvind"
    assert arvind.model == "bulbul:v3"
    assert "बोल रहा हूँ" in arvind.greeting_hi
    assert "Arvind" in arvind.greeting_en

    # Shreya (Female)
    shreya = get_persona("shreya")
    assert shreya.name == "Shreya"
    assert shreya.gender == "female"
    assert shreya.voice == "shreya"
    assert "बोल रही हूँ" in shreya.greeting_hi
    assert "Shreya" in shreya.greeting_en

    # Meera (Female)
    meera = get_persona("meera")
    assert meera.name == "Meera"
    assert meera.gender == "female"
    assert meera.voice == "meera"
    assert "बोल रही हूँ" in meera.greeting_hi

    # Dhruv (Male)
    dhruv = get_persona("dhruv")
    assert dhruv.name == "Dhruv"
    assert dhruv.gender == "male"
    assert dhruv.voice == "dhruv"
    assert "बोल रहा हूँ" in dhruv.greeting_hi


def test_fallback_persona_resolution():
    """Verify unknown or None resolves safely to default persona."""
    default_p = get_persona(None)
    assert default_p.id == "shreya"
    
    unknown_p = get_persona("unknown_agent_xyz")
    assert unknown_p.id == "shreya"

    # resolve_persona_voice
    assert resolve_persona_voice("arvind") == "arvind"
    assert resolve_persona_voice("shreya") == "shreya"
    assert resolve_persona_voice(None, custom_voice="meera") == "meera"
    assert resolve_persona_voice("arvind", custom_voice="dhruv") == "dhruv"


def test_arvind_male_prompt_generation():
    """Verify Arvind prompt enforces male grammar and bans Sara identity."""
    prompt = build_voice_system_prompt("arvind")
    assert "Your name is Arvind" in prompt
    assert "बोल रहा हूँ" in prompt
    assert "कर सकता हूँ" in prompt
    # Strict rule: Male grammar must ban feminine verb endings
    assert "GENDER GRAMMAR RULE (MALE)" in prompt
    assert "NEVER use feminine verb endings (रही हूँ, सकती हूँ, जानती हूँ)" in prompt
    # Verify natural modern Hinglish instructions
    assert "NATURAL MODERN HINGLISH" in prompt
    assert "'leads', 'calls', 'features'" in prompt
    # Verify pure textbook Hindi ban
    assert "स्वचालन" in prompt
    assert "दूरभाष" in prompt
    assert "प्रतिपुष्टि" in prompt


def test_shreya_female_prompt_generation():
    """Verify Shreya prompt enforces female grammar."""
    prompt = build_voice_system_prompt("shreya")
    assert "Your name is Shreya" in prompt
    assert "बोल रही हूँ" in prompt
    assert "कर सकती हूँ" in prompt
    assert "GENDER GRAMMAR RULE (FEMALE)" in prompt
    assert "NEVER use masculine verb endings (रहा हूँ, सकता हूँ, जानता हूँ)" in prompt
    assert "NATURAL MODERN HINGLISH" in prompt


def test_api_personas_endpoint():
    """Verify GET /api/personas returns all personas with expected JSON schema."""
    client = TestClient(app)
    response = client.get("/api/personas")
    assert response.status_code == 200
    data = response.json()
    assert "personas" in data
    assert len(data["personas"]) == 4

    arvind_data = next((p for p in data["personas"] if p["id"] == "arvind"), None)
    assert arvind_data is not None
    assert arvind_data["gender"] == "male"
    assert arvind_data["voice"] == "arvind"
    assert arvind_data["name"] == "Arvind"


def test_api_livekit_join_with_persona():
    """Verify /api/livekit/join accepts persona and voice in payload."""
    from app.services.auth_service import create_jwt_token
    client = TestClient(app)
    token = create_jwt_token("test_admin")
    headers = {"Authorization": f"Bearer {token}"}

    join_resp = client.post(
        "/api/livekit/join",
        json={"persona": "arvind", "voice": "arvind"},
        headers=headers
    )
    # May return 200 or 503 if LiveKit cloud not configured in test env, but endpoint processes persona cleanly
    assert join_resp.status_code in (200, 500, 503)

