"""
Contract tests for the SIGNUPS_ENABLED gate on POST /auth/signup.

WHY this gate exists: tradingDesk verifies Dialectic access tokens with the
same HS256 secret and maps `sub` to a desk user. With signup open to the
internet, anyone could self-register an account whose tokens td would
cryptographically trust. Closing signup removes the door that mints them.

WHY these tests: the gate is only worth having if it fails CLOSED. The
dangerous failure is not "signup rejected when it should work" — it is a
config typo silently reopening registration. So every non-affirmative value
is asserted to 403, and the refusal is asserted to happen BEFORE any database
work (a gate that still writes rows is not a gate).
"""

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")

import api.auth.routes as auth_routes


SIGNUP_BODY = {
    "email": "newcomer@example.com",
    "password": "a-sufficiently-long-password",
    "display_name": "Newcomer",
}


@pytest.fixture
def db():
    """A db whose every call is recorded, so a test can prove it was untouched."""
    fake = AsyncMock()
    fake.fetchrow.return_value = None  # "email not already registered"
    return fake


@pytest.fixture
def client(db):
    """Mount the real auth router with the db dependency overridden."""
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")

    async def _get_db():
        yield db

    app.dependency_overrides[auth_routes.get_db] = _get_db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("SIGNUPS_ENABLED", raising=False)


class TestSignupClosed:
    def test_unset_env_is_403(self, client, db):
        resp = client.post("/auth/signup", json=SIGNUP_BODY)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Signups are closed. Ask Amo for an invite."

    def test_refusal_touches_no_database(self, client, db):
        """A 403 must not create a user, burn a uuid, or probe the email —
        otherwise the endpoint still leaks whether an address is registered."""
        client.post("/auth/signup", json=SIGNUP_BODY)
        assert db.execute.await_count == 0
        assert db.fetchrow.await_count == 0

    @pytest.mark.parametrize(
        "value",
        ["false", "0", "no", "off", "", "  ", "disabled", "TRUE_BUT_TYPO", "yes please"],
    )
    def test_non_affirmative_values_are_403(self, client, monkeypatch, value):
        """Anything not on the allowlist means closed. A typo must not open
        registration — that is the failure mode this gate exists to prevent."""
        monkeypatch.setenv("SIGNUPS_ENABLED", value)
        assert client.post("/auth/signup", json=SIGNUP_BODY).status_code == 403


class TestSignupEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " True "])
    def test_affirmative_values_open_the_gate(self, client, monkeypatch, value, db):
        """The gate must be genuinely reopenable, or it is a deletion with
        extra steps. Asserting the request gets PAST the gate (reaching the db)
        rather than asserting a 200, so this stays about the gate only."""
        monkeypatch.setenv("SIGNUPS_ENABLED", value)
        resp = client.post("/auth/signup", json=SIGNUP_BODY)
        assert resp.status_code != 403
        assert db.fetchrow.await_count > 0, "request never reached the signup body"


class TestFlagHelper:
    """Unit-level checks on the predicate itself, so a failure points at the
    parsing rather than at the HTTP layer."""

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "On", " YES "])
    def test_truthy(self, monkeypatch, value):
        monkeypatch.setenv("SIGNUPS_ENABLED", value)
        assert auth_routes._signups_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe", "2"])
    def test_falsy(self, monkeypatch, value):
        monkeypatch.setenv("SIGNUPS_ENABLED", value)
        assert auth_routes._signups_enabled() is False

    def test_unset_is_false(self, monkeypatch):
        monkeypatch.delenv("SIGNUPS_ENABLED", raising=False)
        assert auth_routes._signups_enabled() is False

    def test_read_at_call_time_not_import_time(self, monkeypatch):
        """The flag must follow the running environment. If it were captured at
        import, flipping it would require a code change rather than a restart."""
        monkeypatch.setenv("SIGNUPS_ENABLED", "true")
        assert auth_routes._signups_enabled() is True
        monkeypatch.setenv("SIGNUPS_ENABLED", "false")
        assert auth_routes._signups_enabled() is False


class TestOtherAuthRoutesUnaffected:
    def test_login_is_not_gated(self, client, db, monkeypatch):
        """The gate must close registration only. If it caught login, closing
        signups would lock Amo and Dan out of their own rooms."""
        monkeypatch.delenv("SIGNUPS_ENABLED", raising=False)
        db.fetchrow.return_value = None  # no such user -> 401, not 403
        resp = client.post(
            "/auth/login",
            json={"email": "amo@example.com", "password": "whatever-long-enough"},
        )
        assert resp.status_code != 403
        assert db.fetchrow.await_count > 0, "login never reached its body"

    def test_forgot_password_is_not_gated(self, client, db):
        db.fetchrow.return_value = None
        resp = client.post("/auth/forgot-password", json={"email": "amo@example.com"})
        assert resp.status_code != 403
