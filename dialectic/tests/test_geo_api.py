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
from deploy import seed_hormuz_geo, seed_room_geo

CALLER_ID = UUID("00000000-0000-0000-0000-000000000701")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000702")
SCOPE_ID = UUID("00000000-0000-0000-0000-000000000703")
SIGNAL_ID = "world_signal:ais:contact-1"
GEO_PATH = f"/rooms/{ROOM_ID}/geo"
SIGNAL_PATH = f"/rooms/{ROOM_ID}/world-signals/{SIGNAL_ID}/place"
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


# ---------------------------------------------------------------------------
# GET /rooms/{room_id}/world/observations — the World Lens consumer's read
# door (Step 4). Same auth as every other geo route (`_obs_client` mirrors
# `_client` exactly); the write semantics live entirely in world_watch.py,
# owned elsewhere — this router never inserts a `world_observations` row.
# ---------------------------------------------------------------------------

WORLD_OBS_PATH = f"/rooms/{ROOM_ID}/world/observations"


def _obs_row(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    row = {
        "id": SCOPE_ID,
        "scope_id": SCOPE_ID,
        "scope_label": "Strait of Hormuz (approx.)",
        "provider": "adsb",
        "signal_id": "world_signal:adsb:contact-1",
        "layer": "aircraft",
        "kind": "point",
        "label": "Contact A",
        "geometry": {"type": "Point", "coordinates": [56.3, 26.5]},
        "provenance": {"provider": "adsb", "acquisition": "adapter", "credit": "ODbL"},
        "details": {},
        "observed_at": now,
        "retrieved_at": now,
        "first_seen_at": now,
        "last_seen_at": now,
        "seen_count": 2,
    }
    row.update(overrides)
    return row


def _obs_client(
    *, authenticated: bool = True, room: bool = True, member: bool = True,
    observation_rows: list[dict] | None = None, count_rows: list[dict] | None = None,
) -> TestClient:
    main_mod.app.dependency_overrides.clear()
    db = AsyncMock()
    calls: list[tuple] = []

    async def fetchrow(sql, *args):
        if "SELECT 1 FROM rooms" in sql:
            return {"?column?": 1} if room else None
        if "SELECT 1 FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        return None

    async def fetch(sql, *args):
        calls.append((sql, args))
        if "GROUP BY wo.scope_id" in sql:
            return count_rows or []
        return observation_rows or []

    db.fetchrow.side_effect = fetchrow
    db.fetch.side_effect = fetch
    db.calls = calls

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[geo_mod.get_db] = db_dependency
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: _caller()
    client = TestClient(main_mod.app)
    client.db = db
    return client


def test_world_observations_requires_bearer_auth():
    assert _obs_client(authenticated=False).get(WORLD_OBS_PATH, headers=HEADERS).status_code == 401


def test_world_observations_refuses_a_wrong_room_token():
    assert _obs_client(room=False).get(WORLD_OBS_PATH, headers=HEADERS).status_code == 401


def test_world_observations_refuses_a_nonmember():
    assert _obs_client(member=False).get(WORLD_OBS_PATH, headers=HEADERS).status_code == 403


def test_world_observations_200_shape():
    client = _obs_client(
        observation_rows=[_obs_row()],
        count_rows=[{
            "scope_id": SCOPE_ID, "scope_label": "Strait of Hormuz (approx.)",
            "layer": "aircraft", "n": 3, "newest_at": datetime.now(timezone.utc),
        }],
    )
    response = client.get(WORLD_OBS_PATH, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert len(body["observations"]) == 1
    obs = body["observations"][0]
    assert obs["scope_id"] == f"geo_scope:{SCOPE_ID}"
    assert obs["scope_label"] == "Strait of Hormuz (approx.)"
    assert obs["provider"] == "adsb"
    assert obs["layer"] == "aircraft"
    assert obs["seen_count"] == 2
    assert obs["geometry"] == {"type": "Point", "coordinates": [56.3, 26.5]}
    assert len(body["counts"]) == 1
    count = body["counts"][0]
    assert count["scope_id"] == f"geo_scope:{SCOPE_ID}"
    assert count["layer"] == "aircraft"
    assert count["count"] == 3


def test_world_observations_empty_shape():
    response = _obs_client().get(WORLD_OBS_PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"observations": [], "counts": []}


def test_world_observations_hours_default_and_clamped_not_rejected():
    client = _obs_client()
    default = client.get(WORLD_OBS_PATH, headers=HEADERS)
    too_low = client.get(WORLD_OBS_PATH, params={"hours": 0}, headers=HEADERS)
    too_high = client.get(WORLD_OBS_PATH, params={"hours": 999}, headers=HEADERS)

    assert default.status_code == too_low.status_code == too_high.status_code == 200
    hours_used = [call[1][1] for call in client.db.calls]
    assert 24 in hours_used  # the unclamped default
    assert 1 in hours_used  # hours=0 clamped up, never rejected
    assert 168 in hours_used  # hours=999 clamped down, never rejected
    assert 0 not in hours_used
    assert 999 not in hours_used


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


def test_signal_placement_requires_bearer_auth_room_token_and_membership():
    assert _client(authenticated=False).post(SIGNAL_PATH, headers=HEADERS).status_code == 401
    assert _client(room=False).post(SIGNAL_PATH, headers=HEADERS).status_code == 401
    assert _client(member=False).post(SIGNAL_PATH, headers=HEADERS).status_code == 403


def test_signal_placement_distinguishes_malformed_and_missing_server_signals():
    malformed = _client().post(
        f"/rooms/{ROOM_ID}/world-signals/not-a-signal/place", headers=HEADERS,
    )
    assert malformed.status_code == 422
    assert "world_signal" in malformed.json()["detail"]

    missing = _client().post(SIGNAL_PATH, headers=HEADERS)
    assert missing.status_code == 404


def test_signal_placement_has_no_client_body_contract():
    route = next(route for route in geo_mod.router.routes if route.path.endswith("/world-signals/{signal_id}/place"))
    assert route.body_field is None


def test_hormuz_seed_requires_named_human_and_inspection_acknowledgement():
    parser = seed_hormuz_geo.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args([
        "--confirmed-by", str(CALLER_ID),
        "--geometry-inspected-by-named-human",
    ])
    assert args.confirmed_by == CALLER_ID
    assert args.geometry_inspected_by_named_human is True


@pytest.mark.asyncio
async def test_seed_refuses_a_real_run_without_the_inspection_acknowledgement():
    # The guard fires BEFORE any connection is opened: no asyncpg patching,
    # so a regression that moved it after the connect would fail loudly here.
    with pytest.raises(SystemExit, match="geometry-inspected-by-named-human"):
        await seed_hormuz_geo.main(seed_hormuz_geo.MANIFEST, CALLER_ID, False)


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

    monkeypatch.setattr(seed_room_geo.asyncpg, "connect", connect)
    await seed_hormuz_geo.main(
        seed_hormuz_geo.MANIFEST, CALLER_ID, False, geometry_inspected=True,
    )

    seeds = seed_room_geo.build_seeds(seed_room_geo.load_manifest(seed_hormuz_geo.MANIFEST))
    expected_by_label = {
        seed.label: seed_room_geo.validate_geometry(seed.kind, seed.geometry) for seed in seeds
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


def test_review_history_requires_the_exact_room_token():
    path = f"{GEO_PATH}/{SCOPE_ID}/review"
    missing = _client().get(path)
    wrong = _client(room=False).get(path, headers={"X-Room-Token": "wrong"})

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Room token required"
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Invalid room token"


def test_review_history_route_serializes_one_complete_lineage(monkeypatch):
    now = datetime.now(timezone.utc)
    current = geo_mod.GeoScope(
        id=f"geo_scope:{SCOPE_ID}", room_id=ROOM_ID,
        subject={"entity": "rooms", "id": str(ROOM_ID)},
        kind="point", geometry=BODY["geometry"], label="Serialized scope",
        authority="human_confirmed",
        provenance={
            "provider": "human", "acquisition": "human", "source_id": "source-7",
            "url": "https://source.test/7", "credit": "Source credit",
        },
        source_state="ok", revision_action="place", review_state="accepted",
        freshness={"state": "not_applicable", "retrieved_at": now},
        centroid=[56.3, 26.5], retrieved_at=now, confirmed_by=CALLER_ID,
        confirmed_at=now, created_by=CALLER_ID, created_at=now,
    )

    async def review(*args: object, **kwargs: object) -> geo_mod.GeoScopeReview:
        return geo_mod.GeoScopeReview(
            root_id=f"geo_scope:{SCOPE_ID}", current=current, lineage=[current],
            subject_destination={"room_id": ROOM_ID},
        )

    monkeypatch.setattr(geo_mod.GeoScopeService, "review", review)
    response = _client().get(f"{GEO_PATH}/{SCOPE_ID}/review", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["root_id"] == f"geo_scope:{SCOPE_ID}"
    assert body["current"]["id"] == f"geo_scope:{SCOPE_ID}"
    assert body["lineage"] == [body["current"]]
    assert body["current"]["provenance"]["url"] == "https://source.test/7"


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
        ("/rooms/{room_id}/world-signals/{signal_id}/place", ("POST",)),
    ]
