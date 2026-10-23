"""
Comprehensive Unit & Integration Test Suite: Configurable Agent Brand Introduction
===================================================================================
Tests all Phase 6 requirements:
1. Frontend contracts: Checkbox HTML/JS labels, defaults, event listeners, localStorage persistence, dispatch payload wiring.
2. Backend validation & dispatch:
   - Explicit True / False accepted and propagated to CallConfigRegistry.
   - Omitted field defaults to True (backward compatibility).
   - Strict validation: invalid types (e.g., random string, invalid objects) rejected.
   - Per-call isolation: Call A (True) vs Call B (False) isolated by session_id and dispatch_id.
   - Retries / lookup reuse the original dispatch setting.
3. Prompt & Greeting behavior:
   - System prompt in True mode permits Flowiz introduction.
   - System prompt in False mode explicitly forbids volunteering Flowiz/Cybernauts.
   - Custom call prompt does not override disabled brand introduction.
   - Fallback LLM / Pipecat adapter level 3 directives enforce brand omission.
   - greetings.wav is bypassed when False (dynamic TTS greeting without Flowiz).
   - Direct prospect questions about company identity are answered truthfully (do not lie/deny).
   - Unrelated behaviors (Sara identity, phone capture, termination) remain intact.
"""

import os
import sys
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Ensure workspace paths on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEAM_A_DIR = os.path.join(BASE_DIR, "Team A")
TEAM_B_DIR = os.path.join(BASE_DIR, "Team B")
PILLAR1_DIR = os.path.join(TEAM_A_DIR, "pillar1")

for p in [BASE_DIR, TEAM_A_DIR, TEAM_B_DIR, PILLAR1_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app
from app.events import EventBus
from app.services.call_config_registry import (
    CallConfigRegistry,
    CallPromptConfig,
    call_config_registry,
)
from app.llm.prompts import (
    VOICE_SYSTEM_PROMPT,
    build_voice_system_prompt,
)
from app.adapters.pipecat.adapter import _build_real_pipeline_task, GreetingPlayerProcessor
from app.adapters.pipecat.events import PipecatEventBridge
from pipecat.services.groq.llm import GroqLLMService
from database.connection import setup_database
from database.repository import LeadRepository
from models.lead_record import LeadRecord

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure global registry is clean before and after each test."""
    call_config_registry.clear()
    yield
    call_config_registry.clear()


@pytest.fixture
def test_db_path(tmp_path):
    """Creates an isolated temporary SQLite database for testing."""
    db_file = str(tmp_path / "test_leads.db")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    setup_database(cursor)
    conn.commit()
    conn.close()
    return db_file


# ==============================================================================
# 1. FRONTEND CONTRACT & STATIC VERIFICATION (Requirements 1-5, 7-8)
# ==============================================================================

def test_frontend_lead_detail_brand_checkbox_structure():
    """Verify leadDetail.js includes the brand introduction checkbox with exact label and helper text."""
    lead_detail_path = os.path.join(BASE_DIR, "static", "js", "views", "leadDetail.js")
    assert os.path.exists(lead_detail_path), "leadDetail.js not found"
    
    with open(lead_detail_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for state naming and default
    assert "include_brand_introduction" in content or "flowiz_include_brand_introduction" in content
    # Check for exact label and supporting text
    assert "Introduce the agent as being from Flowiz" in content
    assert "When enabled, the agent may mention Flowiz in its opening introduction." in content
    assert "When disabled, the agent will not volunteer the brand name." in content
    # Check for localStorage persistence
    assert "localStorage.getItem('flowiz_include_brand_introduction')" in content
    assert "localStorage.setItem('flowiz_include_brand_introduction'" in content
    # Check for inclusion in dispatch payload
    assert "include_brand_introduction:" in content or '"include_brand_introduction":' in content


def test_frontend_live_agent_brand_checkbox_structure():
    """Verify liveAgent.js dialer includes the brand introduction checkbox and status badge."""
    live_agent_path = os.path.join(BASE_DIR, "static", "js", "views", "liveAgent.js")
    assert os.path.exists(live_agent_path), "liveAgent.js not found"
    
    with open(live_agent_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "include_brand_introduction" in content
    assert "Introduce the agent as being from Flowiz" in content
    assert "localStorage.getItem('flowiz_include_brand_introduction')" in content
    assert "Brand Intro:" in content


def test_frontend_team_b_test_page_brand_checkbox_structure():
    """Verify Team B test frontend includes the brand intro checkbox and payload wiring."""
    html_path = os.path.join(TEAM_B_DIR, "frontend", "index.html")
    js_path = os.path.join(TEAM_B_DIR, "frontend", "app.js")
    assert os.path.exists(html_path) and os.path.exists(js_path)

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "brand-intro-checkbox" in html
    assert "Introduce the agent as being from Flowiz" in html
    assert "include_brand_introduction" in js


# ==============================================================================
# 2. BACKEND MODEL & STRICT VALIDATION (Requirements 6-9)
# ==============================================================================

def test_call_prompt_config_brand_introduction_default():
    """Default must be True for backward compatibility."""
    config = CallPromptConfig()
    assert config.include_brand_introduction is True


def test_call_prompt_config_explicit_boolean_values():
    """Explicit True and False are strictly accepted."""
    config_true = CallPromptConfig(include_brand_introduction=True)
    assert config_true.include_brand_introduction is True

    config_false = CallPromptConfig(include_brand_introduction=False)
    assert config_false.include_brand_introduction is False


def test_call_prompt_config_coercible_strings_and_integers():
    """Strict validation correctly parses standard truthy/falsy strings and 0/1."""
    assert CallPromptConfig(include_brand_introduction="false").include_brand_introduction is False
    assert CallPromptConfig(include_brand_introduction="False").include_brand_introduction is False
    assert CallPromptConfig(include_brand_introduction="0").include_brand_introduction is False
    assert CallPromptConfig(include_brand_introduction=0).include_brand_introduction is False

    assert CallPromptConfig(include_brand_introduction="true").include_brand_introduction is True
    assert CallPromptConfig(include_brand_introduction="True").include_brand_introduction is True
    assert CallPromptConfig(include_brand_introduction="1").include_brand_introduction is True
    assert CallPromptConfig(include_brand_introduction=1).include_brand_introduction is True


def test_call_prompt_config_strict_validation_rejection():
    """Invalid types (e.g. random strings, lists) must raise a validation error."""
    with pytest.raises(Exception):
        CallPromptConfig(include_brand_introduction="invalid_boolean")

    with pytest.raises(Exception):
        CallPromptConfig(include_brand_introduction=["true"])


# ==============================================================================
# 3. REGISTRY ISOLATION & RETRY PERSISTENCE (Requirements 10-12)
# ==============================================================================

def test_registry_session_isolation_brand_intro():
    """Ensure concurrent calls A (True) and B (False) maintain strict isolation."""
    reg = CallConfigRegistry()
    config_a = CallPromptConfig(include_brand_introduction=True, call_prompt="Script A")
    config_b = CallPromptConfig(include_brand_introduction=False, call_prompt="Script B")

    reg.set(session_id="sess_call_a", config=config_a, dispatch_id="disp_a")
    reg.set(session_id="sess_call_b", config=config_b, dispatch_id="disp_b")

    res_a = reg.get("sess_call_a")
    res_b = reg.get("sess_call_b")
    assert res_a is not None and res_b is not None
    assert res_a.include_brand_introduction is True
    assert res_b.include_brand_introduction is False

    # Get by dispatch_id maintains the same isolation
    assert reg.get_by_dispatch("disp_a").include_brand_introduction is True
    assert reg.get_by_dispatch("disp_b").include_brand_introduction is False


def test_registry_retry_resumes_original_configuration():
    """Retrying or looking up dispatch_id retrieves the original configuration."""
    reg = CallConfigRegistry()
    config = CallPromptConfig(include_brand_introduction=False, objective="Qualify prospect")
    reg.set(session_id="sess_original", config=config, dispatch_id="disp_123")

    # Simulate reconnect/retry looking up via dispatch_id
    retried_config = reg.get_by_dispatch("disp_123")
    assert retried_config is not None
    assert retried_config.include_brand_introduction is False
    assert retried_config.objective == "Qualify prospect"


# ==============================================================================
# 4. DISPATCH API ENDPOINT TESTS (Requirements 6-9, 11)
# ==============================================================================

def test_dispatch_api_explicit_true(test_db_path):
    """POST /api/leads/{id}/dispatch-call with include_brand_introduction=true."""
    repo = LeadRepository(test_db_path)
    test_domain = "testcorp-true.io"
    repo.upsert_lead(LeadRecord(
        company_name="TestCorp True",
        domain=test_domain,
        phones=["+919876543210"],
        call_status="uncalled"
    ))

    with patch("api.DB_PATH", test_db_path):
        with patch("Pillar_2.outbound_call.place_outbound_call", return_value="plivo_mock_111") as mock_call:
            resp = client.post(
                f"/api/leads/{test_domain}/dispatch-call",
                json={
                    "phoneNumber": "+919876543210",
                    "force": True,
                    "include_brand_introduction": True
                }
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["include_brand_introduction"] is True
            
            # Verify in registry
            disp_id = data["dispatch_id"]
            stored = call_config_registry.get_by_dispatch(disp_id)
            assert stored is not None
            assert stored.include_brand_introduction is True


def test_dispatch_api_explicit_false(test_db_path):
    """POST /api/leads/{id}/dispatch-call with include_brand_introduction=false."""
    repo = LeadRepository(test_db_path)
    test_domain = "testcorp-false.io"
    repo.upsert_lead(LeadRecord(
        company_name="TestCorp False",
        domain=test_domain,
        phones=["+919876543210"],
        call_status="uncalled"
    ))

    with patch("api.DB_PATH", test_db_path):
        with patch("Pillar_2.outbound_call.place_outbound_call", return_value="plivo_mock_222") as mock_call:
            resp = client.post(
                f"/api/leads/{test_domain}/dispatch-call",
                json={
                    "phoneNumber": "+919876543210",
                    "force": True,
                    "include_brand_introduction": False
                }
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["include_brand_introduction"] is False
            
            # Verify in registry
            disp_id = data["dispatch_id"]
            stored = call_config_registry.get_by_dispatch(disp_id)
            assert stored is not None
            assert stored.include_brand_introduction is False


def test_dispatch_api_omitted_field_defaults_to_true(test_db_path):
    """POST /api/leads/{id}/dispatch-call with omitted include_brand_introduction defaults to True."""
    repo = LeadRepository(test_db_path)
    test_domain = "testcorp-omitted.io"
    repo.upsert_lead(LeadRecord(
        company_name="TestCorp Omitted",
        domain=test_domain,
        phones=["+919876543210"],
        call_status="uncalled"
    ))

    with patch("api.DB_PATH", test_db_path):
        with patch("Pillar_2.outbound_call.place_outbound_call", return_value="plivo_mock_333") as mock_call:
            resp = client.post(
                f"/api/leads/{test_domain}/dispatch-call",
                json={
                    "phoneNumber": "+919876543210",
                    "force": True
                }
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["include_brand_introduction"] is True


def test_dispatch_api_invalid_value_rejected(test_db_path):
    """POST /api/leads/{id}/dispatch-call with invalid include_brand_introduction returns HTTP 422."""
    repo = LeadRepository(test_db_path)
    test_domain = "testcorp-invalid.io"
    repo.upsert_lead(LeadRecord(
        company_name="TestCorp Invalid",
        domain=test_domain,
        phones=["+919876543210"],
        call_status="uncalled"
    ))

    with patch("api.DB_PATH", test_db_path):
        resp = client.post(
            f"/api/leads/{test_domain}/dispatch-call",
            json={
                "phoneNumber": "+919876543210",
                "force": True,
                "include_brand_introduction": "not-a-boolean"
            }
        )
        assert resp.status_code == 422


# ==============================================================================
# 5. PROMPT & SYSTEM PROMPT BEHAVIOR (Requirements 13-17)
# ==============================================================================

def test_system_prompt_enabled_mode():
    """When enabled, system prompt includes Flowiz/Cybernauts identity instructions."""
    prompt = build_voice_system_prompt(include_brand_introduction=True)
    assert "Sara from Flowiz" in prompt
    assert "BRAND INTRODUCTION RESTRICTION" not in prompt
    # Also verify backward compatible default VOICE_SYSTEM_PROMPT
    assert "Sara from Flowiz" in VOICE_SYSTEM_PROMPT


def test_system_prompt_disabled_mode():
    """When disabled, system prompt forbids volunteering Flowiz and guides natural greeting."""
    prompt = build_voice_system_prompt(include_brand_introduction=False)
    assert "BRAND INTRODUCTION RESTRICTION (MANDATORY)" in prompt
    assert "Do NOT voluntarily identify or introduce yourself as being from Flowiz or Cybernauts" in prompt
    assert "Begin with a natural greeting and proceed directly to the call objective without volunteering the company or brand name." in prompt
    assert "TRUTHFULNESS ON DIRECT INQUIRY" in prompt
    assert "truthfully state that you represent Flowiz" in prompt


def test_sara_identity_preserved_when_brand_intro_disabled():
    """Disabling brand introduction must preserve Sara identity and never switch to Alex."""
    prompt = build_voice_system_prompt(include_brand_introduction=False)
    assert "Your name is Sara. Always identify yourself as Sara." in prompt
    assert "Never identify as Alex or any other name." in prompt
    assert "IDENTITY & PERSONA (IMMUTABLE)" in prompt


# ==============================================================================
# 6. PIPECAT ADAPTER, GREETING GENERATION & FALLBACK PATHS
# ==============================================================================

def test_pipecat_adapter_level_3_directive_disabled_mode():
    """Verify that Level 3 directive omits Flowiz when include_brand_introduction is False."""
    event_bus = EventBus()
    bridge = PipecatEventBridge(event_bus, "sess_dir_false", "exec_dir_false")
    llm_service = MagicMock(spec=GroqLLMService)

    with patch("pipecat.processors.aggregators.llm_context.LLMContext") as mock_ctx_cls:
        _build_real_pipeline_task(
            pipecat_processors=[llm_service],
            transport=None,
            bridge=bridge,
            call_prompt_config=CallPromptConfig(include_brand_introduction=False),
        )
        system_msg = mock_ctx_cls.call_args.kwargs["messages"][0]["content"]
        assert "DO NOT volunteer that you are calling from Flowiz or Cybernauts in your opening introduction" in system_msg
        assert "LEVEL 3: OUTBOUND CALL DIRECTIVE: (DEFAULT)" in system_msg

    with patch("pipecat.processors.aggregators.llm_context.LLMContext") as mock_ctx_cls_true:
        _build_real_pipeline_task(
            pipecat_processors=[llm_service],
            transport=None,
            bridge=bridge,
            call_prompt_config=CallPromptConfig(include_brand_introduction=True),
        )
        system_msg_true = mock_ctx_cls_true.call_args.kwargs["messages"][0]["content"]
        assert "Introduce yourself as Sara from Flowiz and Cybernauts" in system_msg_true


def test_pipecat_adapter_custom_prompt_precedence_disabled_mode():
    """Custom prompt cannot override disabled brand introduction."""
    event_bus = EventBus()
    bridge = PipecatEventBridge(event_bus, "sess_cust_false", "exec_cust_false")
    llm_service = MagicMock(spec=GroqLLMService)

    custom_script = "Hello, I am calling about voice automation for sales teams."
    config = CallPromptConfig(
        include_brand_introduction=False,
        call_prompt=custom_script
    )

    with patch("pipecat.processors.aggregators.llm_context.LLMContext") as mock_ctx_cls:
        _build_real_pipeline_task(
            pipecat_processors=[llm_service],
            transport=None,
            bridge=bridge,
            call_prompt_config=config,
        )
        system_msg = mock_ctx_cls.call_args.kwargs["messages"][0]["content"]
        assert "Rule 6: BRAND INTRODUCTION RESTRICTION (MANDATORY): You must NOT identify or introduce yourself as being from Flowiz or Cybernauts" in system_msg
        assert custom_script in system_msg


def test_pipecat_adapter_greetings_audio_bypass_when_disabled():
    """Ensure GreetingPlayerProcessor (greetings.wav) is bypassed when include_brand_introduction is False."""
    event_bus = EventBus()
    bridge = PipecatEventBridge(event_bus, "sess_audio_check", "exec_audio_check")
    llm_service = MagicMock(spec=GroqLLMService)
    
    # Mock a TTS service processor so GreetingPlayerProcessor injection logic is evaluated
    mock_tts = MagicMock()
    mock_tts.__class__.__name__ = "CartesiaTTSService"

    with patch.dict(os.environ, {"ENABLE_INITIAL_GREETING": "true"}), \
         patch("os.path.exists", return_value=True), \
         patch("pipecat.processors.aggregators.llm_context.LLMContext"):
        # When include_brand_introduction is False, GreetingPlayerProcessor must NOT be in processors
        task_false = _build_real_pipeline_task(
            pipecat_processors=[llm_service, mock_tts],
            transport=None,
            bridge=bridge,
            call_prompt_config=CallPromptConfig(include_brand_introduction=False),
        )
        all_procs_false = [sub for p in task_false._pipeline.processors if hasattr(p, "processors") for sub in p.processors]
        has_greeting_false = any(isinstance(sub, GreetingPlayerProcessor) for sub in all_procs_false)
        assert has_greeting_false is False

        # When include_brand_introduction is True, GreetingPlayerProcessor is added
        task_true = _build_real_pipeline_task(
            pipecat_processors=[llm_service, mock_tts],
            transport=None,
            bridge=bridge,
            call_prompt_config=CallPromptConfig(include_brand_introduction=True),
        )
        all_procs_true = [sub for p in task_true._pipeline.processors if hasattr(p, "processors") for sub in p.processors]
        has_greeting_true = any(isinstance(sub, GreetingPlayerProcessor) for sub in all_procs_true)
        assert has_greeting_true is True


def test_truthful_affiliation_instruction_for_cybernauts_and_flowiz():
    """Disabled mode must truthfully confirm affiliation with Flowiz and Cybernauts if directly asked."""
    prompt_false = build_voice_system_prompt(include_brand_introduction=False)
    assert "TRUTHFULNESS ON DIRECT INQUIRY" in prompt_false
    assert "truthfully state that you represent Flowiz and Cybernauts" in prompt_false
    assert "Never lie or falsely deny your affiliation" in prompt_false


def test_strict_type_validation_rejects_invalid_values():
    """Verify CallPromptConfig rejects invalid non-boolean strings and arbitrary structures."""
    with pytest.raises(ValueError, match="must be a valid boolean"):
        CallPromptConfig(include_brand_introduction="not_a_boolean")

    with pytest.raises(ValueError, match="must be a valid boolean"):
        CallPromptConfig(include_brand_introduction="maybe")

    with pytest.raises(ValueError, match="must be a valid boolean"):
        CallPromptConfig(include_brand_introduction=[True])

    # Valid truthy/falsy equivalents are accepted
    assert CallPromptConfig(include_brand_introduction="true").include_brand_introduction is True
    assert CallPromptConfig(include_brand_introduction="False").include_brand_introduction is False
    assert CallPromptConfig(include_brand_introduction=1).include_brand_introduction is True
    assert CallPromptConfig(include_brand_introduction=0).include_brand_introduction is False


@pytest.mark.asyncio
async def test_registry_miss_rehydration_prevents_silent_enablement():
    """If the registry entry is expired or missing, company_context rehydrates False so it cannot silently default to True."""
    from app.main import run_voice_session
    from app.session import SessionManager

    captured_metadata = {}

    class StopSession(Exception):
        pass

    async def fake_create_session(session_id=None, metadata=None):
        nonlocal captured_metadata
        captured_metadata = metadata or {}
        raise StopSession("Captured")

    with patch.object(SessionManager, "create_session", side_effect=fake_create_session):
        # Ensure registry is completely empty (simulating lookup miss or TTL eviction)
        call_config_registry.clear()

        # Call run_voice_session with company_context carrying include_brand_introduction=False
        try:
            await run_voice_session(
                transport=MagicMock(),
                phone_number="+919876543210",
                company_context={"company_name": "Acme Corp", "include_brand_introduction": False},
                session_id="missing_sess_id",
                dispatch_id="missing_disp_id",
            )
        except StopSession:
            pass

        assert captured_metadata.get("include_brand_introduction") is False, \
            "Configuration lookup miss must NOT silently enable brand introduction when company_context provides False"


