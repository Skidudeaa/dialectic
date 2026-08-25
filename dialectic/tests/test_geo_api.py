"""
HTTP contract for api/geo.py — the World Lens write door.

Auth/routing/shape use FastAPI dependency overrides + a fake db, mirroring
tests/test_field_api.py. The write semantics (append-only confirm/reject,
the authority guard) live in tests/test_geo_scopes_pg.py against real
Postgres, calling the route helpers directly.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.geo as geo_mod
import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user
from deploy import seed_hormuz_geo

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


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


def _scope_row() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": SCOPE_ID,
        "room_id": ROOM_ID,
        "subject": {"entity": "rooms", "id": str(ROOM_ID)},
        "kind": "point",
        "geometry": {"type": "Point", "coordinates": [56.3, 26.5]},
        "label": "scope",
        "authority": "human_confirmed",
        "provenance": {"provider": "human", "acquisition": "human"},
        "source_state": "ok",
        "observed_at": None,
        "retrieved_at": now,
        "expires_at": None,
        "confirmed_by": CALLER_ID,
        "confirmed_at": now,
        "supersedes_id": None,
        "revision_action": "place",
        "review_note": None,
        "created_by": CALLER_ID,
        "created_at": now,
        "has_successor": False,
    }


def _client(
    *, authenticated: bool = True, room: bool = True, member: bool = True,
    subject_resolves: bool = True, scope: bool = False,
) -> TestClient:
    main_mod.app.dependency_overrides.clear()
    db = AsyncMock()

    async def fetchrow(sql, *args):
        if "SELECT 1 FROM rooms" in sql:
            return {"?column?": 1} if room else None
        if "SELECT 1 FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        if scope and "FROM geo_scopes g" in sql and "FOR UPDATE OF g" in sql:
            return _scope_row()
        return None

    async def fetchval(sql, *args):
        if sql.startswith("SELECT 1 FROM rooms WHERE id"):
            return 1 if subject_resolves else None
        if scope and "SELECT 1 FROM geo_scopes g" in sql:
            return 1
        return None

    db.fetchrow.side_effect = fetchrow
    db.fetchval.side_effect = fetchval
    db.fetch.return_value = []
    db.transaction = lambda: _Transaction()

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


def test_hormuz_seed_requires_named_human_and_inspection_acknowledgement():
    parser = seed_hormuz_geo.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--confirmed-by", str(CALLER_ID)])
    args = parser.parse_args([
        "--confirmed-by", str(CALLER_ID),
        "--geometry-inspected-by-named-human",
    ])
    assert args.confirmed_by == CALLER_ID
    assert args.geometry_inspected_by_named_human is True


@pytest.mark.asyncio
async def test_hormuz_seed_events_include_each_persisted_geometry(monkeypatch):
    class SeedConnection:
        def __init__(self) -> None:
            self.event_payloads: list[dict] = []

        async def set_type_codec(self, *args: object, **kwargs: object) -> None:
            return None

        async def fetchval(self, sql: str, *args: object) -> int | None:
            if "room_memberships" in sql:
                return 1
            return None

        async def execute(self, sql: str, *args: object) -> str:
            if "INSERT INTO events" in sql:
                self.event_payloads.append(args[-1])
            return "INSERT 0 1"

        def transaction(self) -> _Transaction:
            return _Transaction()

        async def close(self) -> None:
            return None

    connection = SeedConnection()

    async def connect(*args: object, **kwargs: object) -> SeedConnection:
        return connection

    monkeypatch.setattr(seed_hormuz_geo.asyncpg, "connect", connect)
    await seed_hormuz_geo.main(
        CALLER_ID, False, geometry_inspected=True,
    )

    expected_by_label = {
        label: geometry for _kind, label, geometry, _provenance in seed_hormuz_geo.SEEDS
    }
    assert len(connection.event_payloads) == len(expected_by_label)
    for payload in connection.event_payloads:
        assert payload["geometry"] == expected_by_label[payload["label"]]


def test_review_routes_require_auth():
    for action in ("confirm", "reject", "ratify", "redraw", "supersede"):
        path = f"{GEO_PATH}/{SCOPE_ID}/{action}"
        body = {"label": "v2", "geometry": BODY["geometry"]} if action == "redraw" else None
        assert _client(authenticated=False).post(path, json=body, headers=HEADERS).status_code == 401
        assert _client(member=False).post(path, json=body, headers=HEADERS).status_code == 403


def test_review_history_requires_auth_and_membership():
    path = f"{GEO_PATH}/{SCOPE_ID}/review"
    assert _client(authenticated=False).get(path, headers=HEADERS).status_code == 401
    assert _client(member=False).get(path, headers=HEADERS).status_code == 403


def test_redraw_rejects_malformed_geometry():
    response = _client(scope=True).post(
        f"{GEO_PATH}/{SCOPE_ID}/redraw",
        json={"label": "bad", "geometry": {"type": "Point", "coordinates": [400, 0]}},
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert "range" in response.json()["detail"]


def test_redraw_refuses_client_owned_subject_or_provenance():
    for stolen in (
        {"subject": {"entity": "rooms", "id": str(ROOM_ID)}},
        {"provenance": {"provider": "client"}},
    ):
        response = _client().post(
            f"{GEO_PATH}/{SCOPE_ID}/redraw",
            json={"label": "bad", "geometry": BODY["geometry"], **stolen},
            headers=HEADERS,
        )
        assert response.status_code == 422


def test_the_routers_write_surface_is_exactly_the_human_authority_actions():
    """No browser route mints a machine proposal or mutates a row in place."""
    writes = sorted(
        (route.path, tuple(sorted(route.methods)))
        for route in geo_mod.router.routes
        if route.methods - {"GET", "HEAD", "OPTIONS"}
    )
    assert writes == [
        ("/rooms/{room_id}/geo", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/confirm", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/ratify", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/redraw", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/reject", ("POST",)),
        ("/rooms/{room_id}/geo/{scope_id}/supersede", ("POST",)),
    ]
