"""
Real-Postgres contracts for the World Lens substrate (geo_scopes.py,
migration 021), plus the two places it plugs in: the Field's subject
allowlist (field_marks.py) and the Atlas fence (atlas_objects.py).

WHY real Postgres: the invariants that matter are properties of what the
SQL returns — the derived live set, the authority guard's predicate, and
the per-viewer fence. A mocked DB would assert a query shape.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/021_geo_scopes.sql
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

import api.geo as geo_api
from api.auth.dependencies import AuthenticatedUser
from atlas_objects import AtlasService
from field_marks import resolve_subjects_in_room
from geo_scopes import (
    GEO_AUTHORITIES,
    GEO_KINDS,
    GEO_SOURCE_STATES,
    GeoScopeService,
    centroid,
    insert_scope,
    validate_geometry,
)

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)
_TS_PATH = Path(__file__).resolve().parents[1] / "frontend/app/src/types/geo.ts"


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-b000-{n:012x}")


AMO, DAN = _uid(0x1), _uid(0x2)
ROOM_AMO, ROOM_DAN = _uid(0x11), _uid(0x12)
READING = _uid(0x41)

RING = [[55.6, 26.0], [56.2, 25.6], [57.2, 25.9], [57.0, 26.9], [55.6, 26.0]]
POLY = {"type": "Polygon", "coordinates": [RING]}
LINE = {"type": "LineString", "coordinates": [[55.3, 26.4], [56.0, 26.6], [57.4, 25.7]]}


def _user(uid: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=uid, email=f"{uid}@test", email_verified=True, display_name="T",
    )


# ---------------------------------------------------------------------------
# pure: geometry
# ---------------------------------------------------------------------------

def test_validate_geometry_accepts_each_kind():
    assert validate_geometry("point", {"type": "Point", "coordinates": [56.3, 26.5]})["coordinates"] == [56.3, 26.5]
    assert validate_geometry("route", LINE)["type"] == "LineString"
    assert validate_geometry("polygon", POLY)["coordinates"][0][-1] == RING[0]
    assert validate_geometry("region", POLY)["type"] == "Polygon"


@pytest.mark.parametrize("kind,geometry,reason", [
    ("polygon", {"type": "Polygon", "coordinates": [RING[:-1]]}, "close"),
    ("polygon", {"type": "Polygon", "coordinates": [RING[:2] + [RING[0]]]}, "four"),
    ("point", {"type": "Point", "coordinates": [200, 0]}, "range"),
    ("point", {"type": "Point", "coordinates": [0, 91]}, "range"),
    ("route", {"type": "LineString", "coordinates": [[0, 0]]}, "two"),
    ("route", POLY, "LineString"),
    ("polygon", LINE, "Polygon"),
    ("point", {"type": "Point", "coordinates": ["56", "26"]}, "lon, lat"),
    ("mountain", POLY, "unknown kind"),
])
def test_validate_geometry_refuses(kind, geometry, reason):
    with pytest.raises(ValueError, match=reason):
        validate_geometry(kind, geometry)


def test_validate_geometry_caps_vertices():
    big = {"type": "LineString", "coordinates": [[0, i * 0.01] for i in range(2001)]}
    with pytest.raises(ValueError, match="too many"):
        validate_geometry("route", big)


def test_centroid_skips_the_closing_vertex():
    # A square's closing vertex would double-weight one corner otherwise.
    square = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    assert centroid(square) == [1.0, 1.0]
    assert centroid({"type": "Point", "coordinates": [5, 6]}) == [5.0, 6.0]


# ---------------------------------------------------------------------------
# contract: the TS side agrees, in order
# ---------------------------------------------------------------------------

def _string_union(source: str, const: str) -> list[str]:
    match = re.search(
        rf"^export const {const} = \[\n(.*?)^\] as const",
        source, re.MULTILINE | re.DOTALL,
    )
    assert match, f"const {const} not found in {_TS_PATH.name}"
    return re.findall(r"'([^']+)'", match.group(1))


@pytest.mark.parametrize("python_values,ts_const", [
    (GEO_KINDS, "GEO_KINDS"),
    (GEO_AUTHORITIES, "GEO_AUTHORITIES"),
    (GEO_SOURCE_STATES, "GEO_SOURCE_STATES"),
])
def test_closed_vocabularies_agree_in_order(python_values, ts_const):
    assert _string_union(_TS_PATH.read_text(), ts_const) == list(python_values)


# ---------------------------------------------------------------------------
# postgres
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    has_table = await conn.fetchval("SELECT to_regclass('geo_scopes')")
    if not has_table:
        await conn.close()
        pytest.skip("migration 021 not applied to the test database")
        return
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def world(db):
    """Two rooms, one member each. AMO's room holds a reading."""
    tx = db.transaction()
    await tx.start()
    now = datetime.now(timezone.utc)
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo'),($3,$2,'Dan')",
        AMO, now, DAN,
    )
    for rid, name in ((ROOM_AMO, "Amo's"), (ROOM_DAN, "Dan's")):
        await db.execute(
            "INSERT INTO rooms (id, name, token, created_at) VALUES ($1,$2,$3,$4)",
            rid, name, f"tok-{rid}", now,
        )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3),($4,$5,$3)",
        ROOM_AMO, AMO, now, ROOM_DAN, DAN,
    )
    await db.execute(
        """INSERT INTO reading_items (id, room_id, url, title, site, content, summary, source, created_at)
           VALUES ($1,$2,'https://example.test/hormuz','Tankers slow','example.test','body','s','wire',$3)""",
        READING, ROOM_AMO, now,
    )
    yield db
    await tx.rollback()


@pytest.mark.asyncio
async def test_insert_and_project_a_human_scope(world):
    sid = await insert_scope(
        world, room_id=ROOM_AMO, subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="polygon", geometry=POLY, label="Strait",
        authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human", "credit": "sketch"},
        confirmed_by=AMO, created_by=AMO,
    )
    projection = await GeoScopeService(world).build(ROOM_AMO)
    assert [s.id for s in projection.scopes] == [f"geo_scope:{sid}"]
    scope = projection.scopes[0]
    assert scope.authority == "human_confirmed"
    assert scope.confirmed_by == AMO and scope.confirmed_at is not None
    assert scope.centroid == centroid(POLY)
    assert scope.provenance.credit == "sketch"


@pytest.mark.asyncio
async def test_the_owning_module_refuses_what_the_check_would(world):
    base = dict(room_id=ROOM_AMO, subject={"entity": "rooms", "id": str(ROOM_AMO)},
                kind="polygon", geometry=POLY,
                provenance={"provider": "human", "acquisition": "human"})
    with pytest.raises(ValueError, match="confirmed_by"):
        await insert_scope(world, authority="human_confirmed", **base)
    with pytest.raises(ValueError, match="confirmed_by"):
        await insert_scope(world, authority="machine_proposed", confirmed_by=AMO, **base)
    with pytest.raises(ValueError, match="acquired by llm"):
        await insert_scope(world, authority="machine_proposed", **base)
    with pytest.raises(ValueError, match="unknown subject entity"):
        await insert_scope(world, authority="human_confirmed", confirmed_by=AMO,
                           **{**base, "subject": {"entity": "attachments", "id": str(READING)}})


async def _propose(world, subject=None):
    return await insert_scope(
        world, room_id=ROOM_AMO,
        subject=subject or {"entity": "reading_items", "id": str(READING)},
        kind="region", geometry=POLY, label="Persian Gulf?",
        authority="machine_proposed",
        provenance={"provider": "natural_earth", "acquisition": "llm",
                    "source_id": "Persian Gulf", "credit": "Made with Natural Earth"},
    )


@pytest.mark.asyncio
async def test_a_proposal_is_live_but_cannot_anchor_a_field_mark(world):
    """The authority guard, asserted to FIRE: the same subject resolves for
    the Field only after a human confirms it."""
    sid = await _propose(world)
    subject = [{"entity": "geo_scopes", "id": str(sid)}]
    assert await GeoScopeService(world).is_live(sid)
    assert await resolve_subjects_in_room(world, ROOM_AMO, subject) is False

    replacement = await geo_api._review(ROOM_AMO, sid, "confirm", _user(AMO), world)
    assert replacement.authority == "human_confirmed"
    assert replacement.supersedes_id == sid
    assert replacement.source_state == "ok"
    assert replacement.geometry == validate_geometry("region", POLY)
    # Derived, never updated in place: the proposal row is untouched but no
    # longer live, and the replacement now anchors a mark.
    assert await world.fetchval("SELECT authority FROM geo_scopes WHERE id = $1", sid) == "machine_proposed"
    assert await GeoScopeService(world).is_live(sid) is False
    live = await GeoScopeService(world).build(ROOM_AMO)
    assert [s.id for s in live.scopes] == [replacement.id]
    new_id = UUID(replacement.id.split(":", 1)[1])
    assert await resolve_subjects_in_room(world, ROOM_AMO, [{"entity": "geo_scopes", "id": str(new_id)}]) is True


@pytest.mark.asyncio
async def test_reject_is_a_confirmed_empty_row_and_hides_both(world):
    sid = await _propose(world)
    replacement = await geo_api._review(ROOM_AMO, sid, "reject", _user(AMO), world)
    assert replacement.source_state == "confirmed_empty"
    assert replacement.supersedes_id == sid
    assert (await GeoScopeService(world).build(ROOM_AMO)).scopes == []
    assert await world.fetchval("SELECT count(*) FROM geo_scopes WHERE room_id = $1", ROOM_AMO) == 2
    # A rejected row cannot anchor a mark either.
    rid = UUID(replacement.id.split(":", 1)[1])
    assert await resolve_subjects_in_room(world, ROOM_AMO, [{"entity": "geo_scopes", "id": str(rid)}]) is False
    events = await world.fetch(
        "SELECT event_type, payload FROM events WHERE room_id = $1 ORDER BY timestamp", ROOM_AMO,
    )
    assert events[-1]["event_type"] == "geo_scope_reviewed"
    assert events[-1]["payload"]["action"] == "reject"


@pytest.mark.asyncio
async def test_review_refuses_what_is_not_a_live_proposal(world):
    sid = await _propose(world)
    await geo_api._review(ROOM_AMO, sid, "confirm", _user(AMO), world)
    with pytest.raises(HTTPException) as exc:
        await geo_api._review(ROOM_AMO, sid, "confirm", _user(AMO), world)
    assert exc.value.status_code == 409
    human = await insert_scope(
        world, room_id=ROOM_AMO, subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="polygon", geometry=POLY, authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human"}, confirmed_by=AMO,
    )
    with pytest.raises(HTTPException) as exc:
        await geo_api._review(ROOM_AMO, human, "reject", _user(AMO), world)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await geo_api._review(ROOM_DAN, sid, "confirm", _user(DAN), world)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_expired_scope_is_not_live(world):
    sid = await insert_scope(
        world, room_id=ROOM_AMO, subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        authority="source_reported",
        provenance={"provider": "adsb.lol", "acquisition": "adapter:adsb", "credit": "adsb.lol ODbL"},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert await GeoScopeService(world).is_live(sid) is False
    assert (await GeoScopeService(world).build(ROOM_AMO)).scopes == []


@pytest.mark.asyncio
async def test_the_subject_must_live_in_the_room(world):
    from geo_scopes import resolve_subject_in_room
    assert await resolve_subject_in_room(world, ROOM_AMO, {"entity": "reading_items", "id": str(READING)})
    assert not await resolve_subject_in_room(world, ROOM_DAN, {"entity": "reading_items", "id": str(READING)})
    assert not await resolve_subject_in_room(world, ROOM_AMO, {"entity": "rooms", "id": str(ROOM_DAN)})
    assert not await resolve_subject_in_room(world, ROOM_AMO, {"entity": "reading_items", "id": "nope"})


@pytest.mark.asyncio
async def test_the_atlas_fence_holds_for_scopes(world):
    """Two viewers of the same table get two different answers (§6.5)."""
    mine = await insert_scope(
        world, room_id=ROOM_AMO, subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="polygon", geometry=POLY, label="AMO-ONLY", authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human"}, confirmed_by=AMO,
    )
    theirs = await insert_scope(
        world, room_id=ROOM_DAN, subject={"entity": "rooms", "id": str(ROOM_DAN)},
        kind="polygon", geometry=POLY, label="DAN-ONLY", authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human"}, confirmed_by=DAN,
    )
    amo_view = await AtlasService(world).build(AMO)
    dan_view = await AtlasService(world).build(DAN)
    assert [s.id for s in amo_view.scopes] == [f"geo_scope:{mine}"]
    assert [s.id for s in dan_view.scopes] == [f"geo_scope:{theirs}"]
    assert all("DAN-ONLY" != s.label for s in amo_view.scopes)
    # The scope's subject resolves to a node the same projection carries.
    assert f"room:{ROOM_AMO}" in {n.id for n in amo_view.nodes}
