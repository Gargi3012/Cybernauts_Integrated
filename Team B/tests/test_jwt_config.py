"""
Tests for JWT configuration consistency, production secret enforcement, and token lifecycle.
Verifies that:
1. .env.example strictly uses 'JWT_SECRET' (and not 'JWT_SECRET_KEY').
2. Development mode allows safe 32-byte fallback when unset.
3. Missing ENVIRONMENT handling (with and without JWT_SECRET).
4. Production mode strictly raises RuntimeError when JWT_SECRET is missing or empty.
5. Production mode strictly raises ValueError when JWT_SECRET is a placeholder or shorter than 32 characters.
6. Production mode signs and verifies tokens securely when a valid 32+ byte secret is provided.
7. Backward compatibility alias 'JWT_SECRET' routes dynamically through get_jwt_secret without static dev fallback in production.
8. Server startup validation enforces production secrets before lifespan initialization.
"""

import os
import sys
from pathlib import Path
import pytest
import jwt

# Ensure repository root is in sys.path
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app.services.auth_service as auth_service_module
from app.services.auth_service import (
    get_jwt_secret,
    create_jwt_token,
    DEV_JWT_FALLBACK_SECRET,
    INSECURE_PLACEHOLDER_SECRETS,
)


def test_env_example_uses_jwt_secret():
    """Verify .env.example defines JWT_SECRET and eliminates obsolete JWT_SECRET_KEY."""
    env_example_path = Path(REPO_ROOT) / ".env.example"
    assert env_example_path.exists(), ".env.example must exist at repo root"

    content = env_example_path.read_text(encoding="utf-8")
    assert "JWT_SECRET=" in content, ".env.example must define JWT_SECRET"
    assert "JWT_SECRET_KEY=" not in content, ".env.example must not use obsolete JWT_SECRET_KEY"


def test_dev_fallback_allowed_when_not_in_production(monkeypatch):
    """Verify development mode allows safe 32-byte fallback when JWT_SECRET is unset."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    secret = get_jwt_secret()
    assert secret == DEV_JWT_FALLBACK_SECRET
    assert len(secret) >= 32, "Development fallback secret must satisfy RFC 7518 32-byte minimum"

    token = create_jwt_token("dev_user")
    assert isinstance(token, str)
    decoded = jwt.decode(token, secret, algorithms=["HS256"])
    assert decoded["sub"] == "dev_user"


def test_missing_environment_with_configured_secret(monkeypatch):
    """Verify missing ENVIRONMENT returns configured JWT_SECRET when provided."""
    custom_secret = "my-custom-test-secret-at-least-32-chars-long"
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("JWT_SECRET", custom_secret)

    secret = get_jwt_secret()
    assert secret == custom_secret


def test_missing_environment_without_secret_uses_dev_fallback(monkeypatch):
    """Verify missing ENVIRONMENT falls back to dev key for local non-production developer convenience."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    secret = get_jwt_secret()
    assert secret == DEV_JWT_FALLBACK_SECRET


def test_production_missing_secret_raises_runtime_error(monkeypatch):
    """Verify production mode fails safely with RuntimeError when JWT_SECRET is missing or empty."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        get_jwt_secret()

    assert "CRITICAL CONFIGURATION ERROR" in str(exc_info.value)
    assert "JWT_SECRET" in str(exc_info.value)

    with pytest.raises(RuntimeError):
        create_jwt_token("prod_user")

    # Also verify empty/whitespace string triggers the same error
    monkeypatch.setenv("JWT_SECRET", "   ")
    with pytest.raises(RuntimeError):
        get_jwt_secret()


def test_production_short_secret_raises_value_error(monkeypatch):
    """Verify production mode rejects secrets shorter than 32 characters (RFC 7518)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "short-16char-key")

    with pytest.raises(ValueError) as exc_info:
        get_jwt_secret()

    assert "at least 32 characters" in str(exc_info.value)


def test_production_placeholder_secrets_rejected(monkeypatch):
    """Verify production mode strictly rejects known insecure placeholder credentials."""
    monkeypatch.setenv("ENVIRONMENT", "production")

    for placeholder in INSECURE_PLACEHOLDER_SECRETS:
        monkeypatch.setenv("JWT_SECRET", placeholder)
        with pytest.raises(ValueError) as exc_info:
            get_jwt_secret()
        assert "insecure" in str(exc_info.value) or "placeholder" in str(exc_info.value)


def test_production_valid_secret_succeeds(monkeypatch):
    """Verify production mode generates and verifies tokens with valid 32+ byte secret."""
    valid_prod_secret = "a" * 32
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", valid_prod_secret)

    secret = get_jwt_secret()
    assert secret == valid_prod_secret

    token = create_jwt_token("secure_admin")
    decoded = jwt.decode(token, valid_prod_secret, algorithms=["HS256"])
    assert decoded["sub"] == "secure_admin"


def test_backward_compat_jwt_secret_alias_dynamic_behavior(monkeypatch):
    """
    Verify accessing auth_service.JWT_SECRET alias dynamically invokes get_jwt_secret
    and strictly enforces production validation rather than using a static dev fallback.
    """
    # 1. In production with missing secret: accessing alias raises RuntimeError
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        _ = auth_service_module.JWT_SECRET

    # 2. In production with valid secret: accessing alias returns valid secret
    valid_prod_secret = "b" * 32
    monkeypatch.setenv("JWT_SECRET", valid_prod_secret)
    assert auth_service_module.JWT_SECRET == valid_prod_secret

    # 3. In development with missing secret: accessing alias returns dev fallback
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert auth_service_module.JWT_SECRET == DEV_JWT_FALLBACK_SECRET


def test_server_startup_validation_production_missing_secret(monkeypatch):
    """Verify server.validate_production_configuration fails safely when JWT_SECRET is missing in production."""
    import server
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        server.validate_production_configuration()

    assert "JWT_SECRET" in str(exc_info.value)


def test_server_startup_validation_production_valid_secret(monkeypatch):
    """Verify server.validate_production_configuration succeeds in production when valid secret is set."""
    import server
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "c" * 32)

    # Must succeed without error
    server.validate_production_configuration()


def test_server_startup_validation_non_production(monkeypatch):
    """Verify server.validate_production_configuration allows startup in development mode without secret."""
    import server
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    # Must succeed without error
    server.validate_production_configuration()
