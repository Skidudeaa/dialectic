"""
HTTP contract for api/geo.py — the World Lens write door.

Auth/routing/shape use FastAPI dependency overrides + a fake db, mirroring
tests/test_field_api.py. The write semantics (append-only confirm/reject,
the authority guard) live in tests/test_geo_scopes_pg.py against real
Postgres, calling the route helpers directly.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

import api.geo as geo_mod
import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user

CALLER_ID = UUID("00000000-0000-0000-0000-000000000701")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000702")
SCOPE_ID = UUID("00000000-0000-0000-0000-000000000703")
GEO_PATH = f"/rooms/{ROOM_ID}/geo"
HEADERS = {"X-Room-Token": "room-token"}
BODY = {
    "subject": {"entity": "rooms", "id": str(ROOM_ID)},
    "kind": "point",
    "geometry": {"type": "Point", "coordinates": [56.3, 26.5]},
}


def setup_function():
    main_mod.app.dependency_overrides.clear()


def teardown_function():
    main_mod.app.dependency_overrides.clear()


def _caller() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True,
        display_name="Caller",
    )


def _client(*, authenticated=True, room=True, member=True, subject_resolves=True) -> TestClient:
    main_mod.app.dependency_overrides.clear()
    db = AsyncMock()

    async def fetchrow(sql, *args):
        if "SELECT 1 FROM rooms" in sql:
            return {"?column?": 1} if room else None
        if "SELECT 1 FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        return None

    async def fetchval(sql, *args):
        if sql.startswith("SELECT 1 FROM rooms WHERE id"):
            return 1 if subject_resolves else None
        return None

    db.fetchrow.side_effect = fetchrow
    db.fetchval.side_effect = fetchval
    db.fetch.return_value = []

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[geo_mod.get_db] = db_dependency
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: _caller()
    return TestClient(main_mod.app)


def test_get_requires_bearer_auth():
    assert _client(authenticated=False).get(GEO_PATH, headers=HEADERS).status_code == 401


def test_get_requires_a_room_token():
    assert _client().get(GEO_PATH).status_code in (401, 422)


def test_get_refuses_a_wrong_room_token():
    assert _client(room=False).get(GEO_PATH, headers=HEADERS).status_code == 401


def test_get_refuses_a_nonmember():
    assert _client(member=False).get(GEO_PATH, headers=HEADERS).status_code == 403


def test_get_returns_an_empty_projection_envelope():
    response = _client().get(GEO_PATH, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["room_id"] == str(ROOM_ID)
    assert body["scopes"] == []
    assert body["generated_at"]


def test_create_requires_bearer_auth():
    assert _client(authenticated=False).post(GEO_PATH, json=BODY, headers=HEADERS).status_code == 401


def test_create_refuses_a_nonmember():
    assert _client(member=False).post(GEO_PATH, json=BODY, headers=HEADERS).status_code == 403


def test_create_refuses_an_unknown_kind():
    resp = _client().post(GEO_PATH, json={**BODY, "kind": "mountain"}, headers=HEADERS)
    assert resp.status_code == 422


def test_create_refuses_a_subject_outside_the_room():
    """The subject check runs in SQL before any insert — a document is not a
    trust boundary."""
    resp = _client(subject_resolves=False).post(GEO_PATH, json=BODY, headers=HEADERS)
    assert resp.status_code == 422
    assert "subject" in resp.json()["detail"]


def test_create_refuses_bad_geometry_before_sql():
    bad = {**BODY, "geometry": {"type": "Point", "coordinates": [400, 0]}}
    resp = _client().post(GEO_PATH, json=bad, headers=HEADERS)
    assert resp.status_code == 422


def test_review_routes_require_auth():
    for action in ("confirm", "reject"):
        path = f"{GEO_PATH}/{SCOPE_ID}/{action}"
        assert _client(authenticated=False).post(path, headers=HEADERS).status_code == 401
        assert _client(member=False).post(path, headers=HEADERS).status_code == 403


def test_the_routers_write_surface_is_exactly_these_three():
    """Enumerated, so a fourth mutation arrives as a failing test. There is
    deliberately NO route that mints machine_proposed rows: the participant
    proposes through an LLM tool, never through anything a browser reaches."""
    writes = sorted(
        (route.path, tuple(sorted(route.methods)))
        for route in geo_mod.router.routes
        if route.methods - {"GET", "HEAD", "OPTIONS"}
    )
    assert writes == [
        ("/rooms/{room_id}/geo", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/confirm", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/reject", ("POST",)),
    ]
