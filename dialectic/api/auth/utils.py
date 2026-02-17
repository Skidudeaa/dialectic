# api/auth/utils.py - JWT and password utilities
"""
ARCHITECTURE: Stateless utilities for token creation and password hashing.
WHY: Centralized security functions ensure consistent handling across endpoints.
TRADEOFF: Requires JWT_SECRET_KEY env var (no fallback for security).
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

# Configuration - JWT_SECRET_KEY (or JWT_SECRET) must be set in environment.
# Lazily evaluated to avoid import-time crashes before env vars are set.
_secret_key_cache: Optional[str] = None


def _get_secret_key() -> str:
    global _secret_key_cache
    if _secret_key_cache is None:
        key = os.environ.get("JWT_SECRET_KEY") or os.environ.get("JWT_SECRET")
        if not key:
            raise RuntimeError(
                "JWT_SECRET_KEY environment variable is required. "
                "Generate one with: openssl rand -hex 32"
            )
        _secret_key_cache = key
    return _secret_key_cache


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 90

# Password hashing with Argon2 (recommended settings)
password_hash = PasswordHash.recommended()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    Uses Argon2 algorithm for memory-hard, GPU-resistant comparison.
    """
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using Argon2.
    Returns a string suitable for database storage.
    """
    return password_hash.hash(password)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a short-lived access token for API authentication.
    Default expiration: 15 minutes.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc),
    })
    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Create a long-lived refresh token for session persistence.
    Default expiration: 90 days (per CONTEXT.md session duration).
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.now(timezone.utc),
    })
    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.
    Raises jwt.InvalidTokenError if token is invalid or expired.
    """
    return jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])


def generate_verification_code() -> str:
    """
    Generate a 6-digit verification code for email verification or password reset.
    Uses cryptographically secure random number generation.
    """
    return ''.join(secrets.choice('0123456789') for _ in range(6))


def hash_refresh_token(token: str) -> str:
    """
    Hash a refresh token for storage in the database.
    We don't need reversibility, just comparison.
    """
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()
