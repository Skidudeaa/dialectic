"""
HTTP contract for GET /users/me/home/activity (api/home.py).

Auth is JWT + current Home membership only — no room token. Missing Home
and authenticated nonmembership are indistinguishable 404s by design.
The projection semantics are proven against real Postgres in
tests/test_home_activity_pg.py; this pins the HTTP door.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.home as home_mod
import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user
from home_activity import (
    HomeActivityProjection,
    HomeActivityRoom,
    HomeUnavailable,
)

CALLER_ID = UUID("00000000-0000-0000-0000-000000000401")

PROJECTION = HomeActivityProjection(
    generated_at=datetime(2026, 8, 12, 5, 0, tzinfo=timezone.utc),
    rooms=[HomeActivityRoom(
        id=UUID("00000000-0000-0000-0000-000000000402"),
        name="Shared Scheme",
        last_message_at=None,
        last_speaker=None,
        last_message_preview=None,
        unread_count=2,
        branches=[],
        unresolved_questions=[],
        commitments_due=[],
    )],
)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main_mod.app.dependency_overrides.clear()


def _client(*, authenticated: bool = True) -> TestClient:
    async def db_dependency() -> AsyncIterator[object]:
        yield AsyncMock()

    main_mod.app.dependency_overrides[home_mod.get_db] = db_dependency
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER_ID,
            email="caller@test",
            email_verified=True,
            display_name="Caller",
        )
    return TestClient(main_mod.app)


def test_activity_requires_bearer_auth() -> None:
    assert _client(authenticated=False).get(
        "/users/me/home/activity"
    ).status_code == 401


def test_activity_returns_projection_without_tokens(monkeypatch) -> None:
    fake_service = SimpleNamespace(build=AsyncMock(return_value=PROJECTION))
    monkeypatch.setattr(
        home_mod,
        "HomeActivityService",
        lambda _db: fake_service,
    )
    response = _client().get("/users/me/home/activity")
    assert response.status_code == 200
    assert "token" not in response.text.lower()
    assert response.json()["rooms"][0]["unread_count"] == 2
    fake_service.build.assert_awaited_once_with(CALLER_ID)


def test_nonmember_and_missing_home_are_indistinguishable(monkeypatch) -> None:
    monkeypatch.setattr(
        home_mod,
        "HomeActivityService",
        lambda _db: SimpleNamespace(
            build=AsyncMock(side_effect=HomeUnavailable())
        ),
    )
    nonmember = _client().get("/users/me/home/activity")
    missing = _client().get("/users/me/home/activity")
    assert (nonmember.status_code, nonmember.json()) == (
        404, {"detail": "Home unavailable"}
    )
    assert (missing.status_code, missing.json()) == (
        nonmember.status_code, nonmember.json()
    )
