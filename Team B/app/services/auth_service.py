import hashlib
import os
import uuid
import jwt
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import User
from typing import Optional

# Known insecure placeholder secrets that must never be permitted in production/staging
KNOWN_INSECURE_SECRETS = {
    "super-secret-key",
    "secret",
    "jwt-secret",
    "your-jwt-secret",
    "change-me",
    "changeme",
    "admin",
    "password",
    "default",
    "test",
    "dummy",
    "your-api-secret",
}

DEV_FALLBACK_JWT_SECRET = "flowiz-development-jwt-signing-key-32bytes-min-token-auth!"

def validate_jwt_secret(secret: Optional[str] = None, environment: Optional[str] = None) -> str:
    """
    Validate and return JWT signing secret.
    Enforces RFC 7518 Section 3.2 (minimum 32 bytes / 256 bits for HS256) in production and staging.
    In development/testing, falls back safely to DEV_FALLBACK_JWT_SECRET if unset or placeholder.
    """
    env = (environment or os.getenv("ENVIRONMENT", "development")).strip().lower()
    is_prod_or_staging = env in ("production", "staging", "prod")

    raw_val = secret if secret is not None else os.getenv("JWT_SECRET", "")
    val = (raw_val or "").strip()

    if is_prod_or_staging:
        if not val:
            raise ValueError(f"JWT_SECRET must be explicitly configured in {env} environment.")
        if val.lower() in KNOWN_INSECURE_SECRETS:
            raise ValueError(f"Insecure placeholder JWT_SECRET is prohibited in {env} environment.")
        if len(val.encode("utf-8")) < 32:
            raise ValueError(
                f"JWT_SECRET is too weak ({len(val.encode('utf-8'))} bytes). "
                f"Minimum 32 bytes (256 bits) required for HMAC-SHA256 (RFC 7518)."
            )
        return val
    else:
        # Development / test mode
        if not val or val.lower() in KNOWN_INSECURE_SECRETS:
            return DEV_FALLBACK_JWT_SECRET
        return val

def get_jwt_secret() -> str:
    """Retrieve the active, validated JWT secret."""
    return validate_jwt_secret()

# Expose JWT_SECRET dynamically or as a property for backward compatibility
JWT_SECRET = get_jwt_secret()

def hash_password(password: str) -> str:
    """Hash password securely using standard PBKDF2-SHA256 (zero dependencies)."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + "$" + key.hex()

def verify_password(stored_hash: str, password: str) -> bool:
    """Verify password by rehashing it and comparing with stored hash."""
    try:
        salt_hex, key_hex = stored_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return new_key == key
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def create_jwt_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed HS256 JWT token valid for 24 hours (or expires_delta)."""
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + (expires_delta if expires_delta is not None else timedelta(hours=24)),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")

async def seed_default_user_if_empty(db: AsyncSession) -> None:
    """Verify if the users table is empty. If empty, seed a default admin user."""
    try:
        result = await db.execute(select(User))
        existing_users = result.scalars().all()
        if not existing_users:
            default_username = os.getenv("ADMIN_USERNAME", "admin")
            default_password = os.getenv("ADMIN_PASSWORD", "admin123")
            
            hashed_pwd = hash_password(default_password)
            default_admin = User(
                username=default_username,
                hashed_password=hashed_pwd
            )
            db.add(default_admin)
            await db.commit()
            logger.info(f"SECURITY: Seeded default admin user '{default_username}' in Neon database.")
    except Exception as e:
        logger.error(f"Failed to seed default user: {e}")
        await db.rollback()
