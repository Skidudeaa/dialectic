"""
HTTP contract for GET /rooms/{room_id}/workspace/objects (api/workspace.py).

The projection semantics are proven against real Postgres in
tests/test_workspace_objects_pg.py; this pins the DOOR — both credentials, the
kind filter, and the read-only shape of the router itself.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.workspace as workspace_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user

CALLER_ID = UUID("00000000-0000-0000-0000-000000000501")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000502")
PATH = f"/rooms/{ROOM_ID}/workspace/objects"
HEADERS = {"X-Room-Token": "room-token"}


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main_mod.app.dependency_overrides.clear()


def _client(*, authenticated: bool = True, room: bool = True,
            member: bool = True) -> TestClient:
    db = AsyncMock()

    async def fetchrow(sql, *args):
        # Matched on the AUTH statements specifically: the thesis adapter also
        # selects FROM rooms, and a looser match would hand it an auth row and
        # fail on a column it never asked for.
        if "SELECT 1 FROM rooms" in sql:
            return {"?column?": 1} if room else None
        if "SELECT 1 FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        return None

    db.fetchrow.side_effect = fetchrow
    db.fetch.return_value = []

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[workspace_mod.get_db] = db_dependency
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER_ID,
            email="caller@test",
            email_verified=True,
            display_name="Caller",
        )
    return TestClient(main_mod.app)


def test_projection_requires_bearer_auth() -> None:
    assert _client(authenticated=False).get(
        PATH, headers=HEADERS
    ).status_code == 401


def test_projection_requires_a_room_token() -> None:
    """Both credentials, exactly as every other room endpoint: identity alone
    must not open a room's contents."""
    assert _client().get(PATH).status_code in (401, 422)


def test_a_wrong_room_token_is_refused() -> None:
    assert _client(room=False).get(PATH, headers=HEADERS).status_code == 401


def test_a_nonmember_is_refused() -> None:
    assert _client(member=False).get(PATH, headers=HEADERS).status_code == 403


def test_a_member_gets_a_projection_envelope() -> None:
    response = _client().get(PATH, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["room_id"] == str(ROOM_ID)
    assert body["objects"] == []
    assert body["generated_at"]


def test_an_unknown_kind_filter_is_refused() -> None:
    """A typo'd kind must not silently return everything — an empty-looking
    surface and a misspelled filter are different problems."""
    assert _client().get(
        PATH, params={"kind": "readings"}, headers=HEADERS
    ).status_code == 400


def test_the_router_exposes_no_write_route() -> None:
    """C4 asserted where it lives: read-only is a property of the router.

    A projection endpoint that grows a POST is how an adapter quietly becomes
    a second write path for entities that already have one.
    """
    methods = {
        method
        for route in workspace_mod.router.routes
        for method in getattr(route, "methods", set())
    }
    assert methods <= {"GET", "HEAD", "OPTIONS"}, methods
