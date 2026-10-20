import hashlib
import os
import uuid
import jwt
from datetime import datetime, timedelta, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import User

# Development fallback secret (32-byte key compliant with RFC 7518)
DEV_JWT_FALLBACK_SECRET = "dev-insecure-jwt-secret-key-32bytes-min!!"

# Known insecure placeholder secrets that must never be accepted in production
INSECURE_PLACEHOLDER_SECRETS = frozenset({
    "change-this-to-a-secure-random-32-byte-secret-in-production",
    "your_jwt_secret_here",
    "super-secret-key",
    "supersecretflowizkey2026",
    DEV_JWT_FALLBACK_SECRET,
})


def get_jwt_secret() -> str:
    """
    Retrieve JWT_SECRET securely from environment.
    In production environments (ENVIRONMENT=production/prod), strictly requires a 32+ character
    secret and fails safely with a clear configuration error if missing, placeholder, or too short.
    In non-production environments, permits a 32-byte dev fallback to maintain developer ergonomics.
    """
    secret = os.getenv("JWT_SECRET")
    env = os.getenv("ENVIRONMENT", "").strip().lower()
    is_production = env in ("production", "prod")

    if not secret or not secret.strip():
        if is_production:
            raise RuntimeError(
                "CRITICAL CONFIGURATION ERROR: 'JWT_SECRET' environment variable is missing in production. "
                "A secure 32+ character secret is required in .env to sign and verify JWT authentication tokens."
            )
        logger.warning(
            "JWT_SECRET is not configured; using insecure development fallback key. "
            "Never use this configuration in production!"
        )
        return DEV_JWT_FALLBACK_SECRET

    secret_clean = secret.strip()

    if is_production:
        if secret_clean in INSECURE_PLACEHOLDER_SECRETS:
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: 'JWT_SECRET' in production is set to an insecure "
                "or placeholder value. Generate a unique, cryptographically random secret of at least 32 characters."
            )
        if len(secret_clean) < 32:
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: 'JWT_SECRET' in production must be at least 32 characters long "
                "for secure HMAC-SHA256 signing (RFC 7518 Section 3.2)."
            )

    return secret_clean


def __getattr__(name: str):
    """
    Safely handle legacy backward-compatibility imports of JWT_SECRET without
    permitting unsafe module-level static fallback in production.
    """
    if name == "JWT_SECRET":
        return get_jwt_secret()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

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

def create_jwt_token(username: str) -> str:
    """Create a signed HS256 JWT token valid for 24 hours."""
    secret = get_jwt_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "exp": now + timedelta(hours=24),
        "iat": now
    }
    return jwt.encode(payload, secret, algorithm="HS256")

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
