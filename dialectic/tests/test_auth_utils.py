"""Tests for api/auth/utils.py — JWT and password utilities."""

import os
import re
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
import jwt as pyjwt

# Set JWT secret before importing the module (lazy-evaluated)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")

from api.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    get_password_hash,
    generate_verification_code,
    hash_refresh_token,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    _get_secret_key,
)


# ── create_access_token ──


class TestCreateAccessToken:
    def test_returns_string(self):
        """create_access_token returns a non-empty string."""
        token = create_access_token({"sub": "user123"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_subject(self):
        """Token payload includes the original data."""
        token = create_access_token({"sub": "user123"})
        payload = decode_token(token)
        assert payload["sub"] == "user123"

    def test_token_has_type_access(self):
        """Access token has type='access' in payload."""
        token = create_access_token({"sub": "test"})
        payload = decode_token(token)
        assert payload["type"] == "access"

    def test_token_has_expiry(self):
        """Access token includes 'exp' claim."""
        token = create_access_token({"sub": "test"})
        payload = decode_token(token)
        assert "exp" in payload

    def test_token_has_issued_at(self):
        """Access token includes 'iat' claim."""
        token = create_access_token({"sub": "test"})
        payload = decode_token(token)
        assert "iat" in payload

    def test_custom_expiry_delta(self):
        """Custom expires_delta is respected."""
        token = create_access_token(
            {"sub": "test"},
            expires_delta=timedelta(hours=2),
        )
        payload = decode_token(token)
        # Expiry should be ~2 hours from now, not the default 15 min
        assert payload["exp"] - payload["iat"] >= 7100  # ~2h in seconds

    def test_does_not_mutate_input(self):
        """Input dict is not modified."""
        data = {"sub": "user123"}
        original = data.copy()
        create_access_token(data)
        assert data == original


# ── decode_token ──


class TestDecodeToken:
    def test_decode_valid_token(self):
        """Valid token decodes successfully."""
        token = create_access_token({"sub": "user42", "role": "admin"})
        payload = decode_token(token)
        assert payload["sub"] == "user42"
        assert payload["role"] == "admin"

    def test_decode_rejects_expired_token(self):
        """Expired token raises InvalidTokenError."""
        token = create_access_token(
            {"sub": "test"},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(pyjwt.exceptions.ExpiredSignatureError):
            decode_token(token)

    def test_decode_rejects_tampered_token(self):
        """Token signed with different secret is rejected."""
        bad_token = pyjwt.encode(
            {"sub": "hacker", "type": "access"},
            "wrong-secret",
            algorithm=ALGORITHM,
        )
        with pytest.raises(pyjwt.exceptions.InvalidSignatureError):
            decode_token(bad_token)

    def test_decode_rejects_malformed_token(self):
        """Completely malformed string raises an error."""
        with pytest.raises(Exception):
            decode_token("not.a.real.token.at.all")


# ── create_refresh_token ──


class TestCreateRefreshToken:
    def test_returns_string(self):
        """create_refresh_token returns a string."""
        token = create_refresh_token({"sub": "user123"})
        assert isinstance(token, str)

    def test_refresh_token_has_type_refresh(self):
        """Refresh token has type='refresh' in payload."""
        token = create_refresh_token({"sub": "test"})
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_refresh_token_long_expiry(self):
        """Refresh token expires much later than access token."""
        access = create_access_token({"sub": "test"})
        refresh = create_refresh_token({"sub": "test"})
        a_payload = decode_token(access)
        r_payload = decode_token(refresh)
        # Refresh should expire days later
        assert r_payload["exp"] > a_payload["exp"]


# ── verify_password / get_password_hash ──


class TestPasswordHashing:
    def test_verify_correct_password(self):
        """verify_password returns True for the correct password."""
        hashed = get_password_hash("my-secret-password")
        assert verify_password("my-secret-password", hashed) is True

    def test_verify_wrong_password(self):
        """verify_password returns False for an incorrect password."""
        hashed = get_password_hash("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self):
        """Hashed password should not contain the original password."""
        hashed = get_password_hash("supersecret")
        assert "supersecret" not in hashed

    def test_different_passwords_different_hashes(self):
        """Different passwords produce different hashes."""
        h1 = get_password_hash("password1")
        h2 = get_password_hash("password2")
        assert h1 != h2

    def test_same_password_different_hashes(self):
        """Same password hashed twice produces different hashes (salting)."""
        h1 = get_password_hash("same-password")
        h2 = get_password_hash("same-password")
        assert h1 != h2


# ── generate_verification_code ──


class TestVerificationCode:
    def test_returns_string(self):
        """generate_verification_code returns a string."""
        code = generate_verification_code()
        assert isinstance(code, str)

    def test_six_digits(self):
        """Code is exactly 6 digits."""
        code = generate_verification_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_format_matches_pattern(self):
        """Code matches the pattern \\d{6}."""
        code = generate_verification_code()
        assert re.fullmatch(r"\d{6}", code)

    def test_codes_are_not_constant(self):
        """Multiple calls produce different codes (probabilistically)."""
        codes = {generate_verification_code() for _ in range(50)}
        # 50 codes should produce at least 2 unique values
        assert len(codes) > 1


# ── hash_refresh_token ──


class TestHashRefreshToken:
    def test_returns_hex_string(self):
        """hash_refresh_token returns a hex-encoded SHA-256 hash."""
        h = hash_refresh_token("some-token-value")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        """Same token always produces the same hash."""
        h1 = hash_refresh_token("token-abc")
        h2 = hash_refresh_token("token-abc")
        assert h1 == h2

    def test_different_input_different_hash(self):
        """Different tokens produce different hashes."""
        h1 = hash_refresh_token("token-1")
        h2 = hash_refresh_token("token-2")
        assert h1 != h2


# ── _get_secret_key ──


class TestGetSecretKey:
    def test_returns_configured_key(self):
        """_get_secret_key returns the env var value."""
        key = _get_secret_key()
        assert isinstance(key, str)
        assert len(key) > 0
