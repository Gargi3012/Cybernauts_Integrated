import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
from app.services.auth_service import hash_password, create_jwt_token

client = TestClient(app)

@pytest.mark.asyncio
async def test_control_plane_endpoints_require_auth():
    # 1. Join endpoint returns 401/403 without authorization header
    response = client.post("/api/livekit/join", json={})
    assert response.status_code in (401, 403)

    # 2. Outbound endpoint returns 401/403 without authorization header
    response = client.post("/api/plivo/outbound", json={"phoneNumber": "+917082968702"})
    assert response.status_code in (401, 403)

@pytest.mark.asyncio
async def test_login_and_access_with_valid_jwt(db_session):
    from app.db.models import User
    from sqlalchemy.future import select

    # Mock user query in database to return our test user
    test_pwd_hash = hash_password("mypassword123")
    
    # We patch the database query to return a mock User model
    mock_user = User(
        username="testadmin",
        hashed_password=test_pwd_hash
    )
    
    # Run login POST request
    with patch("sqlalchemy.ext.asyncio.AsyncSession.execute") as mock_exec:
        # Mocking db return value for user lookup
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_user
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_exec.return_value = mock_result
        
        # Test successful login
        login_res = client.post("/api/login", json={"username": "testadmin", "password": "mypassword123"})
        assert login_res.status_code == 200
        token = login_res.json().get("token")
        assert token is not None

        # Test failed login with wrong password
        failed_res = client.post("/api/login", json={"username": "testadmin", "password": "wrongpassword"})
        assert failed_res.status_code == 401

    # Test accessing endpoints with valid token
    headers = {"Authorization": f"Bearer {token}"}
    
    # Livekit Join needs TRANSPORT_MODE to be livekit
    with patch.dict("os.environ", {"TRANSPORT_MODE": "livekit", "LIVEKIT_API_KEY": "key", "LIVEKIT_API_SECRET": "secret"}):
        with patch("app.main.run_voice_session") as mock_run:
            # We patchAccessToken so that it doesn't try to query actual LiveKit server or fail on SDK
            with patch("livekit.api.AccessToken.to_jwt") as mock_jwt:
                mock_jwt.return_value = "mock_livekit_token"
                res = client.post("/api/livekit/join", json={}, headers=headers)
                assert res.status_code == 200
                assert res.json()["token"] == "mock_livekit_token"


def test_validate_jwt_secret_production_enforcement():
    from app.services.auth_service import validate_jwt_secret
    from datetime import timedelta

    # 1. Missing secret in production
    with pytest.raises(ValueError, match="must be explicitly configured"):
        validate_jwt_secret("", environment="production")

    # 2. Empty/whitespace secret in production
    with pytest.raises(ValueError, match="must be explicitly configured"):
        validate_jwt_secret("   ", environment="production")

    # 3. Known placeholder secret in production
    with pytest.raises(ValueError, match="Insecure placeholder"):
        validate_jwt_secret("super-secret-key", environment="production")

    with pytest.raises(ValueError, match="Insecure placeholder"):
        validate_jwt_secret("change-me", environment="staging")

    # 4. Secret below required minimum strength (< 32 bytes)
    with pytest.raises(ValueError, match="too weak"):
        validate_jwt_secret("only-20-chars-secret", environment="production")

    # 5. Valid production-strength secret (>= 32 bytes)
    valid_prod_key = "a_very_strong_cryptographic_secret_with_32_bytes_min!"
    result = validate_jwt_secret(valid_prod_key, environment="production")
    assert result == valid_prod_key

    # 6. Separate development/test configuration falls back safely without error
    dev_fallback = validate_jwt_secret("", environment="development")
    assert len(dev_fallback.encode("utf-8")) >= 32
    assert dev_fallback != ""


def test_jwt_token_validation_claims_and_expiry():
    import jwt
    from datetime import datetime, timedelta
    from app.services.auth_service import create_jwt_token, get_jwt_secret

    secret = get_jwt_secret()

    # 1. Expired token is rejected with 401
    expired_token = jwt.encode(
        {"sub": "testuser", "exp": datetime.utcnow() - timedelta(minutes=5), "iat": datetime.utcnow() - timedelta(minutes=10)},
        secret,
        algorithm="HS256",
    )
    res = client.post("/api/plivo/outbound", json={"phoneNumber": "+917082968702"}, headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert "expired" in res.json().get("detail", "").lower()

    # 2. Invalid signature is rejected with 403
    wrong_secret = "completely_different_key_with_at_least_32_bytes_length!"
    forged_token = jwt.encode({"sub": "testuser", "exp": datetime.utcnow() + timedelta(hours=1)}, wrong_secret, algorithm="HS256")
    res = client.post("/api/plivo/outbound", json={"phoneNumber": "+917082968702"}, headers={"Authorization": f"Bearer {forged_token}"})
    assert res.status_code == 403

    # 3. Missing subject claim is rejected with 403
    no_sub_token = jwt.encode({"exp": datetime.utcnow() + timedelta(hours=1)}, secret, algorithm="HS256")
    res = client.post("/api/plivo/outbound", json={"phoneNumber": "+917082968702"}, headers={"Authorization": f"Bearer {no_sub_token}"})
    assert res.status_code == 403
    assert "subject claim" in res.json().get("detail", "").lower()

    # 4. Valid token with expected claims succeeds
    valid_token = create_jwt_token("validuser")
    # Endpoint requires auth; verify it passes auth layer
    res = client.post("/api/telephony/hangup", json={"call_id": "call-123"}, headers={"Authorization": f"Bearer {valid_token}"})
    # Auth passed, call proceeds to Plivo client check (either 200 or 500 credentials not configured, but NOT 401/403)
    assert res.status_code in (200, 500)
    assert res.status_code not in (401, 403)


def test_hangup_endpoints_require_jwt_auth():
    # Hangup endpoint returns 401/403 without authorization header
    res1 = client.post("/api/telephony/hangup", json={"call_id": "test_id"})
    assert res1.status_code in (401, 403)

    res2 = client.post("/api/plivo/hangup-call", json={"call_id": "test_id"})
    assert res2.status_code in (401, 403)

