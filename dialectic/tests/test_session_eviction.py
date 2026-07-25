"""
Contracts for multi-device session eviction and how it is explained.

WHY: MAX_SESSIONS_PER_USER evicts a user's least-recently-used session on
their next login. That part is intentional — the bug was that it happened
*silently*: the evicted device learned about it only when /auth/refresh
returned a flat 401 identical to an expired token, and the app dropped to a
blank sign-in form. These tests pin both halves — that eviction records why,
and that refresh reports it.
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

# Must precede the api.auth imports — the JWT helpers read this at first use.
# Matches tests/test_auth_utils.py.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.auth.routes as auth_routes
from api.auth.routes import (
    MAX_SESSIONS_PER_USER,
    REVOKED_BY_LOGOUT,
    REVOKED_BY_NEW_LOGIN,
    REVOKED_BY_PASSWORD_RESET,
    _create_session,
)
from api.auth.utils import create_refresh_token, hash_refresh_token

USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")
OLDEST_SESSION_ID = UUID("00000000-0000-0000-0000-0000000000b1")


def _executed(fake_db):
    """[(query, params), ...] for every db.execute call."""
    return [(c.args[0], c.args[1:]) for c in fake_db.execute.call_args_list]


# ── eviction records a reason ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eviction_at_limit_records_why_it_revoked():
    fake_db = AsyncMock()
    fake_db.fetchval = AsyncMock(return_value=MAX_SESSIONS_PER_USER)  # at limit
    fake_db.fetchrow = AsyncMock(return_value={"id": OLDEST_SESSION_ID})

    await _create_session(fake_db, USER_ID, "refresh-tok", datetime.now(timezone.utc))

    revokes = [(q, p) for q, p in _executed(fake_db) if "revoked_at" in q]
    assert len(revokes) == 1, "exactly one session evicted"
    query, params = revokes[0]
    assert "revoked_reason" in query
    assert OLDEST_SESSION_ID in params
    assert REVOKED_BY_NEW_LOGIN in params


@pytest.mark.asyncio
async def test_no_eviction_below_limit():
    fake_db = AsyncMock()
    fake_db.fetchval = AsyncMock(return_value=MAX_SESSIONS_PER_USER - 1)
    fake_db.fetchrow = AsyncMock(return_value=None)

    await _create_session(fake_db, USER_ID, "refresh-tok", datetime.now(timezone.utc))

    assert not [q for q, _ in _executed(fake_db) if "revoked_at" in q]
    # ...but the new session is still created.
    assert any("INSERT INTO user_sessions" in q for q, _ in _executed(fake_db))


# ── refresh explains the revocation ────────────────────────────────────────

@pytest.fixture
def refresh_client():
    """
    TestClient + a fake db whose single session row the test can shape.
    Yields (client, refresh_token, session_row, fake_db) — mutate session_row
    in place to model a revoked/expired session.
    """
    refresh_token = create_refresh_token(data={"sub": str(USER_ID)})
    session_row = {
        "id": uuid4(),
        "user_id": USER_ID,
        "revoked_at": None,
        "revoked_reason": None,
        "unexpired": True,
    }

    fake_db = AsyncMock()
    fake_db.fetchrow = AsyncMock(return_value=session_row)
    fake_db.execute = AsyncMock(return_value="UPDATE 1")

    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[auth_routes.get_db] = _fake_db_dep
    try:
        yield TestClient(main_mod.app), refresh_token, session_row, fake_db
    finally:
        main_mod.app.dependency_overrides.clear()


def test_live_session_refreshes_normally(refresh_client):
    client, refresh_token, _, _ = refresh_client

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_evicted_device_is_told_it_was_signed_out_elsewhere(refresh_client):
    """The headline fix: a named reason instead of a bare 401."""
    client, refresh_token, session_row, _ = refresh_client
    session_row["revoked_at"] = datetime.now(timezone.utc)
    session_row["revoked_reason"] = REVOKED_BY_NEW_LOGIN

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert "signed in on another device" in detail
    assert str(MAX_SESSIONS_PER_USER) in detail, "says how many devices are allowed"
    # Machine-readable code for clients that want to branch on it.
    assert resp.headers["X-Session-Revoked-Reason"] == REVOKED_BY_NEW_LOGIN


def test_password_reset_revocation_is_explained(refresh_client):
    client, refresh_token, session_row, _ = refresh_client
    session_row["revoked_at"] = datetime.now(timezone.utc)
    session_row["revoked_reason"] = REVOKED_BY_PASSWORD_RESET

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 401
    assert "password was changed" in resp.json()["detail"]


def test_unknown_reason_falls_back_to_generic_message(refresh_client):
    """
    Sessions revoked before revoked_reason existed have NULL. Say nothing
    rather than inventing an explanation.
    """
    client, refresh_token, session_row, _ = refresh_client
    session_row["revoked_at"] = datetime.now(timezone.utc)
    session_row["revoked_reason"] = None

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Session not found or revoked"
    assert "X-Session-Revoked-Reason" not in resp.headers


def test_expired_session_is_not_dressed_up_as_an_eviction(refresh_client):
    """Expiry is not a revocation — it must not borrow the eviction copy."""
    client, refresh_token, session_row, _ = refresh_client
    session_row["unexpired"] = False
    session_row["revoked_reason"] = REVOKED_BY_NEW_LOGIN  # stale, must be ignored

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Session not found or revoked"


def test_unknown_token_is_rejected(refresh_client):
    client, refresh_token, _, _ = refresh_client

    # No row for this hash.
    resp_db = AsyncMock()
    resp_db.fetchrow = AsyncMock(return_value=None)

    async def _empty_db():
        yield resp_db

    main_mod.app.dependency_overrides[auth_routes.get_db] = _empty_db
    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Session not found or revoked"


# ── logout tags its own revocation ─────────────────────────────────────────

def test_logout_records_its_reason(refresh_client):
    """A user-initiated sign-out is tagged as such, not left NULL."""
    client, refresh_token, _, fake_db = refresh_client

    resp = client.post("/auth/logout", json={"refresh_token": refresh_token})

    assert resp.status_code == 200
    revokes = [
        (c.args[0], c.args[1:]) for c in fake_db.execute.call_args_list
        if "revoked_at" in c.args[0]
    ]
    assert len(revokes) == 1
    query, params = revokes[0]
    assert "revoked_reason" in query
    assert hash_refresh_token(refresh_token) in params
    assert REVOKED_BY_LOGOUT in params


def test_reason_constants_are_distinct():
    """Guards against a copy-paste collision silently merging two causes."""
    reasons = {REVOKED_BY_LOGOUT, REVOKED_BY_NEW_LOGIN, REVOKED_BY_PASSWORD_RESET}
    assert len(reasons) == 3
