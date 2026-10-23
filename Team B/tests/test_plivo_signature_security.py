import os
import time
import base64
import hmac
import hashlib
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app, validate_plivo_request, _SEEN_PLIVO_NONCES
import plivo.utils


@pytest.fixture
def client():
    from app.main import APP_STATE
    APP_STATE["is_ready"] = True
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_nonces():
    _SEEN_PLIVO_NONCES.clear()
    yield
    _SEEN_PLIVO_NONCES.clear()


def compute_v2_signature(url: str, nonce: str, auth_token: str) -> str:
    """Helper to compute deterministic Plivo V2 signature."""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
    payload = (base_url + nonce).encode("utf-8")
    sig = hmac.new(auth_token.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8").strip()


def compute_v3_signature(method: str, url: str, nonce: str, auth_token: str, params: dict = None) -> str:
    """Helper to compute deterministic Plivo V3 signature."""
    import six
    from plivo.utils.signature_v3 import construct_post_url, construct_get_url, get_signature_v3
    params = params or {}
    if method.upper() == "GET":
        base_url = construct_get_url(url, params).decode("utf-8")
    else:
        base_url = construct_post_url(url, params).decode("utf-8")
    return get_signature_v3(auth_token.encode("utf-8"), base_url, nonce.encode("utf-8")).decode("utf-8")


def test_plivo_v2_valid_signature_accepted(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    base_url = "https://voice.flowiz.ai"
    path = "/plivo/inbound-call"
    full_url = f"{base_url}{path}"
    nonce = f"nonce_{time.time()}_v2"
    signature = compute_v2_signature(full_url, nonce, auth_token)

    headers = {
        "X-Plivo-Signature-V2": signature,
        "X-Plivo-Signature-V2-Nonce": nonce,
        "Host": "voice.flowiz.ai",
    }
    data = {
        "From": "+919876543210",
        "To": "+911234567890",
        "CallUUID": "call-uuid-v2-test",
    }

    with patch.dict("os.environ", {"ENVIRONMENT": "staging", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        res = client.post(path, data=data, headers=headers)
        assert res.status_code == 200
        assert "<Response>" in res.text
        assert "<Stream" in res.text


def test_plivo_v3_valid_signature_accepted(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    base_url = "https://voice.flowiz.ai"
    path = "/plivo/inbound-call"
    full_url = f"{base_url}{path}"
    nonce = f"nonce_{time.time()}_v3"
    data = {
        "From": "+919876543210",
        "To": "+911234567890",
        "CallUUID": "call-uuid-v3-test",
    }
    signature = compute_v3_signature("POST", full_url, nonce, auth_token, data)

    headers = {
        "X-Plivo-Signature-V3": signature,
        "X-Plivo-Signature-V3-Nonce": nonce,
        "Host": "voice.flowiz.ai",
    }

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        res = client.post(path, data=data, headers=headers)
        assert res.status_code == 200
        assert "<Response>" in res.text


def test_missing_signature_rejected_in_production(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "call-1"}

    # In production without signature header -> 403 Forbidden
    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token}):
        res = client.post("/plivo/inbound-call", data=data)
        assert res.status_code == 403
        assert "Forbidden" in res.json()["detail"]


def test_invalid_signature_rejected_in_production(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "call-1"}
    headers = {
        "X-Plivo-Signature-V2": "invalid_forged_signature_value==",
        "X-Plivo-Signature-V2-Nonce": "fake_nonce_123",
    }

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": "https://voice.flowiz.ai"}):
        res = client.post("/plivo/inbound-call", data=data, headers=headers)
        assert res.status_code == 403


def test_wrong_url_signature_rejected(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    nonce = f"nonce_{time.time()}_wrong_url"
    # Signature calculated for /other-endpoint, but submitted to /plivo/inbound-call
    wrong_url = "https://voice.flowiz.ai/other-endpoint"
    signature = compute_v2_signature(wrong_url, nonce, auth_token)

    headers = {
        "X-Plivo-Signature-V2": signature,
        "X-Plivo-Signature-V2-Nonce": nonce,
    }
    data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "call-1"}

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": "https://voice.flowiz.ai"}):
        res = client.post("/plivo/inbound-call", data=data, headers=headers)
        assert res.status_code == 403


def test_modified_params_v3_signature_rejected(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    base_url = "https://voice.flowiz.ai"
    path = "/plivo/inbound-call"
    full_url = f"{base_url}{path}"
    nonce = f"nonce_{time.time()}_tampered"
    original_data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "call-1"}
    signature = compute_v3_signature("POST", full_url, nonce, auth_token, original_data)

    headers = {
        "X-Plivo-Signature-V3": signature,
        "X-Plivo-Signature-V3-Nonce": nonce,
    }
    # Tampered params
    tampered_data = dict(original_data)
    tampered_data["From"] = "+919999999999"

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        res = client.post(path, data=tampered_data, headers=headers)
        assert res.status_code == 403


def test_replay_attack_rejected(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    base_url = "https://voice.flowiz.ai"
    path = "/plivo/inbound-call"
    full_url = f"{base_url}{path}"
    nonce = f"replay_nonce_{time.time()}"
    signature = compute_v2_signature(full_url, nonce, auth_token)

    headers = {
        "X-Plivo-Signature-V2": signature,
        "X-Plivo-Signature-V2-Nonce": nonce,
    }
    data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "call-1"}

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        # First request succeeds
        res1 = client.post(path, data=data, headers=headers)
        assert res1.status_code == 200

        # Exact replay with same nonce is rejected
        res2 = client.post(path, data=data, headers=headers)
        assert res2.status_code == 403


def test_concurrent_duplicate_webhook_replay(client):
    import concurrent.futures
    auth_token = "valid_staging_plivo_auth_token_123456"
    base_url = "https://voice.flowiz.ai"
    path = "/plivo/inbound-call"
    full_url = f"{base_url}{path}"
    nonce = f"concurrent_nonce_{time.time()}"
    signature = compute_v2_signature(full_url, nonce, auth_token)

    headers = {
        "X-Plivo-Signature-V2": signature,
        "X-Plivo-Signature-V2-Nonce": nonce,
    }
    data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "call-concurrent-1"}

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(client.post, path, data=data, headers=headers)
            fut2 = executor.submit(client.post, path, data=data, headers=headers)
            res1 = fut1.result()
            res2 = fut2.result()

        statuses = sorted([res1.status_code, res2.status_code])
        # Exactly one request must succeed (200) and the duplicate must be rejected (403)
        assert statuses == [200, 403]


def test_hangup_webhook_enforces_signature(client):
    auth_token = "valid_staging_plivo_auth_token_123456"
    base_url = "https://voice.flowiz.ai"
    path = "/plivo/hangup"
    data = {"lead_id": "test-lead-123", "CallUUID": "call-hangup-1"}

    # 1. Unsigned request in production is rejected
    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        res_bad = client.post(path, data=data)
        assert res_bad.status_code == 403

    # 2. Signed request in production is accepted
    nonce = f"hangup_nonce_{time.time()}"
    signature = compute_v2_signature(f"{base_url}{path}", nonce, auth_token)
    headers = {
        "X-Plivo-Signature-V2": signature,
        "X-Plivo-Signature-V2-Nonce": nonce,
    }

    with patch.dict("os.environ", {"ENVIRONMENT": "production", "PLIVO_AUTH_TOKEN": auth_token, "PUBLIC_BASE_URL": base_url}):
        res_good = client.post(path, data=data, headers=headers)
        assert res_good.status_code == 200
        assert res_good.json() == {"status": "hangup_recorded"}


def test_development_mode_allows_unsigned_webhooks(client):
    # In development mode, missing signature does not block developer testing
    data = {"From": "+919876543210", "To": "+911234567890", "CallUUID": "dev-call"}
    with patch.dict("os.environ", {"ENVIRONMENT": "development"}):
        res = client.post("/plivo/inbound-call", data=data)
        assert res.status_code == 200
        assert "<Response>" in res.text
