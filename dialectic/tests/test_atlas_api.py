"""
HTTP contract for GET /users/me/atlas (api/atlas.py).

The projection semantics (the per-viewer fence, node/edge coverage, bounds)
are proven against real Postgres in tests/test_atlas_pg.py; this pins the
DOOR — JWT-only auth, no room-token requirement, and the read-only shape of
the router itself.

WHY a private app rather than api.main.app: api/atlas.py is deliberately NOT
registered on api/main.py yet (§5.0's wire-up ordering — shared registration
files land last, in the orchestrator's own commit). Mounting only this
router keeps every assertion here true regardless of when that wiring lands,
mirroring tests/test_workspace_api.py's dependency-override style without
depending on api/main.py at all.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.atlas as atlas_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user

CALLER_ID = UUID("00000000-0000-0000-0000-000000000701")
PATH = "/users/me/atlas"


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(atlas_mod.router)
    return app


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield


def _client(*, authenticated: bool = True) -> TestClient:
    app = _app()
    db = AsyncMock()
    db.fetch.return_value = []
    db.fetchrow.return_value = None
    db.fetchval.return_value = None
    # `is_in_transaction` is a SYNC method on the real asyncpg.Connection, but
    # AsyncMock makes every attribute async by default -- a plain lambda
    # keeps `if self.db.is_in_transaction():` from evaluating a never-awaited
    # coroutine (always truthy, but a resource-warning either way).
    db.is_in_transaction = lambda: True

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    app.dependency_overrides[atlas_mod.get_db] = db_dependency
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER_ID,
            email="caller@test",
            email_verified=True,
            display_name="Caller",
        )
    return TestClient(app)


def test_atlas_requires_bearer_auth() -> None:
    assert _client(authenticated=False).get(PATH).status_code == 401


def test_atlas_needs_no_room_token() -> None:
    """The whole point of Atlas: no single room's credential gates a
    cross-room projection. A bare JWT, with no X-Room-Token header at all,
    must succeed."""
    response = _client().get(PATH)
    assert response.status_code == 200


def test_a_caller_with_no_rooms_gets_an_empty_projection() -> None:
    response = _client().get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["generated_at"]


def test_default_atlas_response_remains_source_compatible_without_signal_fields() -> None:
    body = _client().get(PATH).json()
    assert set(body) == {"generated_at", "nodes", "edges", "scopes"}


def test_signals_are_opt_in_and_absence_is_explicitly_not_configured() -> None:
    response = _client().get(f"{PATH}?signals=1")
    assert response.status_code == 200
    body = response.json()
    assert body["signals"] == []
    assert body["signal_sources"] == {
        "status": "not_configured",
        "sources": [],
    }


def test_the_router_exposes_no_write_route() -> None:
    """Read-only is a property of the router, not a promise in a docstring —
    same assertion test_workspace_api.py makes for the workspace router."""
    methods = {
        method
        for route in atlas_mod.router.routes
        for method in getattr(route, "methods", set())
    }
    assert methods <= {"GET", "HEAD", "OPTIONS"}, methods


def test_the_router_exposes_exactly_one_route() -> None:
    """Atlas is one endpoint by design (§5.4) -- a second route here would be
    a second, undocumented door onto the same data."""
    assert len(atlas_mod.router.routes) == 1
    assert atlas_mod.router.routes[0].path == "/users/me/atlas"
