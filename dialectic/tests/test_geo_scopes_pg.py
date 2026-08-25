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

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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
    live_predicate,
    validate_geometry,
)
from world_signals import WorldSignal, WorldSignalSnapshot, WorldSignalStore

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)
_TS_PATH = Path(__file__).resolve().parents[1] / "frontend/app/src/types/geo.ts"


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-b000-{n:012x}")


AMO, DAN = _uid(0x1), _uid(0x2)
ROOM_AMO, ROOM_DAN = _uid(0x11), _uid(0x12)
READING = _uid(0x41)
THREAD, MESSAGE = _uid(0x51), _uid(0x61)

RING = [[55.6, 26.0], [56.2, 25.6], [57.2, 25.9], [57.0, 26.9], [55.6, 26.0]]
POLY = {"type": "Polygon", "coordinates": [RING]}
LINE = {"type": "LineString", "coordinates": [[55.3, 26.4], [56.0, 26.6], [57.4, 25.7]]}


def _world_signal(
    source_id: str, *, room_id: UUID = ROOM_AMO,
    expires_at: datetime | None = None,
) -> WorldSignal:
    now = datetime.now(timezone.utc)
    return WorldSignal(
        id=f"world_signal:ais:{source_id}", provider="ais", source_id=source_id,
        room_id=room_id, layer="vessels", kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        provenance={
            "provider": "ais", "acquisition": "adapter:ais",
            "source_id": source_id, "url": f"https://provider.test/{source_id}",
            "credit": "AIS provider credit",
        },
        source_state="partial", freshness="current", coverage="receiver footprint",
        observed_at=now - timedelta(minutes=2),
        retrieved_at=now - timedelta(minutes=1),
        expires_at=expires_at or now + timedelta(minutes=10),
        label=f"Contact {source_id}", details={"speed_knots": 12.4},
    )


def _signal_snapshot(*signals: WorldSignal) -> WorldSignalSnapshot:
    now = datetime.now(timezone.utc)
    return WorldSignalSnapshot(
        provider="ais",
        configured_room_ids=frozenset(signal.room_id for signal in signals),
        source_state="partial", freshness="current",
        coverage="receiver footprint", retrieved_at=now,
        expires_at=now + timedelta(minutes=10), signals=signals,
    )


def _signal_store(*signals: WorldSignal) -> WorldSignalStore:
    store = WorldSignalStore()
    store.replace(_signal_snapshot(*signals))
    return store


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


def test_live_predicate_is_alias_aware_and_refuses_unsafe_aliases():
    predicate = live_predicate("placed_scope")
    assert "placed_scope.expires_at" in predicate
    assert "geo_scope_successor.supersedes_id = placed_scope.id" in predicate
    with pytest.raises(ValueError, match="invalid SQL alias"):
        live_predicate("scope; DELETE")


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
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,'Main')",
        THREAD, ROOM_AMO, now,
    )
    await db.execute(
        """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content)
           VALUES ($1,$2,1,$3,'human',$4,'text','Hormuz claim')""",
        MESSAGE, THREAD, now, AMO,
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
async def test_geo_scope_rows_are_database_enforced_append_only(world):
    """An accidental UPDATE or DELETE must fail even outside the owner module."""
    scope_id = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="polygon", geometry=POLY, label="Immutable Strait",
        authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human"},
        confirmed_by=AMO, created_by=AMO,
    )

    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        async with world.transaction():
            await world.execute(
                "UPDATE geo_scopes SET label = 'mutated' WHERE id = $1", scope_id,
            )
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        async with world.transaction():
            await world.execute("DELETE FROM geo_scopes WHERE id = $1", scope_id)


@pytest.mark.asyncio
async def test_scope_keeps_source_review_and_freshness_as_separate_axes(world):
    observed_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    scope_id = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        authority="source_reported", source_state="partial",
        provenance={"provider": "ais", "acquisition": "adapter:ais"},
        observed_at=observed_at,
    )

    scope = await GeoScopeService(world).get(ROOM_AMO, scope_id)
    assert scope is not None
    assert scope.source_state == "partial"
    assert scope.review_state == "accepted"
    assert scope.revision_action == "place_signal"
    assert scope.freshness.state == "current"
    assert scope.freshness.observed_at == observed_at


@pytest.mark.asyncio
async def test_ratify_appends_an_identical_human_confirmed_successor(world):
    observed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    scope_id = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "reading_items", "id": str(READING)},
        kind="route", geometry=LINE, label="AIS lane",
        authority="source_reported", source_state="partial",
        provenance={
            "provider": "ais", "acquisition": "adapter:ais",
            "source_id": "lane-7", "credit": "AIS source",
        },
        observed_at=observed_at, expires_at=expires_at,
    )
    original = await GeoScopeService(world).get(ROOM_AMO, scope_id)
    assert original is not None

    successor = await geo_api._review(
        ROOM_AMO, scope_id, "ratify", _user(AMO), world,
    )

    assert successor.revision_action == "ratify"
    assert successor.authority == "human_confirmed"
    assert successor.subject == original.subject
    assert successor.provenance == original.provenance
    assert successor.geometry == original.geometry
    assert successor.label == original.label
    assert successor.source_state == original.source_state
    assert successor.observed_at == original.observed_at
    assert successor.retrieved_at == original.retrieved_at
    assert successor.expires_at == original.expires_at
    assert successor.supersedes_id == scope_id
    retired = await GeoScopeService(world).get(ROOM_AMO, scope_id)
    assert retired is not None and retired.review_state == "superseded"


@pytest.mark.asyncio
async def test_ratify_route_accepts_a_legacy_human_confirmed_seed_scope(world):
    scope_id = uuid4()
    now = datetime.now(timezone.utc)
    subject = {"entity": "rooms", "id": str(ROOM_AMO)}
    provenance = {
        "provider": "natural_earth", "acquisition": "human",
        "source_id": "Persian Gulf", "credit": "Made with Natural Earth",
    }
    await world.execute(
        """INSERT INTO geo_scopes
               (id, room_id, subject, kind, geometry, label, authority,
                provenance, source_state, confirmed_by, confirmed_at,
                created_by, created_at)
           VALUES ($1, $2, $3, 'region', $4, 'Persian Gulf',
                   'human_confirmed', $5, 'ok', $6, $7, $6, $7)""",
        scope_id, ROOM_AMO, subject, POLY, provenance, AMO, now,
    )
    original = await GeoScopeService(world).get(ROOM_AMO, scope_id)
    assert original is not None

    successor = await geo_api.ratify_geo_scope(
        ROOM_AMO, scope_id, request=None, token=f"tok-{ROOM_AMO}",
        current_user=_user(AMO), db=world,
    )

    assert successor.revision_action == "ratify"
    assert successor.authority == "human_confirmed"
    assert successor.confirmed_by == AMO
    assert successor.created_by == AMO
    assert successor.subject == original.subject
    assert successor.provenance == original.provenance
    assert successor.geometry == original.geometry
    assert successor.label == original.label
    assert successor.source_state == original.source_state
    assert successor.supersedes_id == scope_id


@pytest.mark.asyncio
async def test_one_scope_cannot_fork_to_two_direct_successors(world):
    scope_id = await _propose(world)
    await geo_api._review(ROOM_AMO, scope_id, "confirm", _user(AMO), world)

    with pytest.raises(asyncpg.UniqueViolationError):
        async with world.transaction():
            await insert_scope(
                world, room_id=ROOM_AMO,
                subject={"entity": "reading_items", "id": str(READING)},
                kind="region", geometry=POLY, label="Fork",
                authority="human_confirmed",
                provenance={"provider": "human", "acquisition": "human"},
                confirmed_by=AMO, supersedes_id=scope_id,
                revision_action="confirm",
            )


@pytest.mark.asyncio
async def test_legacy_confirmed_empty_derives_rejected_without_rewrite(world):
    legacy_id = _uid(0x710)
    now = datetime.now(timezone.utc)
    await world.execute(
        """INSERT INTO geo_scopes
               (id, room_id, subject, kind, geometry, label, authority,
                provenance, retrieved_at, source_state, confirmed_by,
                confirmed_at, revision_action, created_by, created_at)
           VALUES ($1,$2,$3,'point',$4,'legacy rejection','human_confirmed',
                   $5,$6,'confirmed_empty',$7,$6,NULL,$7,$6)""",
        legacy_id, ROOM_AMO, {"entity": "rooms", "id": str(ROOM_AMO)},
        {"type": "Point", "coordinates": [56.3, 26.5]},
        {"provider": "human", "acquisition": "human"}, now, AMO,
    )

    legacy = await GeoScopeService(world).get(ROOM_AMO, legacy_id)
    assert legacy is not None
    assert legacy.revision_action == "reject"
    assert legacy.review_state == "rejected"
    assert legacy.source_state == "confirmed_empty"
    assert await GeoScopeService(world).is_live(legacy_id) is False


@pytest.mark.asyncio
async def test_redraw_copies_server_owned_subject_and_provenance(world):
    scope_id = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "reading_items", "id": str(READING)},
        kind="region", geometry=POLY, label="Old Gulf",
        authority="human_confirmed",
        provenance={
            "provider": "natural_earth", "acquisition": "human",
            "source_id": "Persian Gulf", "credit": "Made with Natural Earth",
        },
        confirmed_by=AMO, created_by=AMO,
    )
    old = await GeoScopeService(world).get(ROOM_AMO, scope_id)
    assert old is not None
    replacement_geometry = {
        "type": "Polygon",
        "coordinates": [[[55.0, 25.0], [56.0, 25.0], [56.0, 26.0], [55.0, 25.0]]],
    }

    successor = await geo_api._review(
        ROOM_AMO, scope_id, "redraw", _user(AMO), world,
        review_note="shoreline corrected", replacement_label="Corrected Gulf",
        replacement_geometry=replacement_geometry,
    )

    assert successor.revision_action == "redraw"
    assert successor.review_note == "shoreline corrected"
    assert successor.label == "Corrected Gulf"
    assert successor.geometry == replacement_geometry
    assert successor.subject == old.subject
    assert successor.provenance == old.provenance


@pytest.mark.asyncio
async def test_supersede_retires_the_chain_without_corrupting_source_state(world):
    scope_id = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        authority="source_reported", source_state="partial",
        provenance={"provider": "sensor", "acquisition": "adapter:sensor"},
        observed_at=datetime.now(timezone.utc),
    )
    ratified = await geo_api._review(
        ROOM_AMO, scope_id, "ratify", _user(AMO), world,
    )
    ratified_id = UUID(ratified.id.split(":", 1)[1])
    retired = await geo_api._review(
        ROOM_AMO, ratified_id, "supersede", _user(AMO), world,
        review_note="no longer relevant",
    )

    assert retired.revision_action == "supersede"
    assert retired.review_state == "rejected"
    assert retired.source_state == "partial"
    assert (await GeoScopeService(world).build(ROOM_AMO)).scopes == []


@pytest.mark.asyncio
async def test_full_lineage_resolves_room_reading_and_exact_message_destination(world):
    service = GeoScopeService(world)
    for entity, subject_id, expected in (
        ("rooms", ROOM_AMO, {"room_id": ROOM_AMO}),
        ("reading_items", READING, {
            "room_id": ROOM_AMO, "object_id": f"reading:{READING}",
        }),
        ("messages", MESSAGE, {
            "room_id": ROOM_AMO, "thread_id": THREAD, "message_id": MESSAGE,
        }),
    ):
        root = await insert_scope(
            world, room_id=ROOM_AMO,
            subject={"entity": entity, "id": str(subject_id)},
            kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
            authority="human_confirmed",
            provenance={"provider": "human", "acquisition": "human"},
            confirmed_by=AMO, created_by=AMO,
        )
        successor = await geo_api._review(
            ROOM_AMO, root, "redraw", _user(AMO), world,
            replacement_label="v2",
            replacement_geometry={"type": "Point", "coordinates": [56.4, 26.6]},
        )
        review = await service.review(
            ROOM_AMO, UUID(successor.id.split(":", 1)[1]),
        )
        assert review is not None
        assert review.root_id == f"geo_scope:{root}"
        assert review.current.id == successor.id
        assert [row.revision_action for row in review.lineage] == ["place", "redraw"]
        destination = review.subject_destination.model_dump(exclude_none=True)
        assert destination == expected


@pytest.mark.asyncio
async def test_lineage_returns_more_than_five_hundred_revisions_without_truncation(world):
    predecessor = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human"},
        confirmed_by=AMO, revision_action="place",
    )
    root_id = predecessor
    chain_ids = [root_id]
    for revision in range(1, 505):
        predecessor = await insert_scope(
            world, room_id=ROOM_AMO,
            subject={"entity": "rooms", "id": str(ROOM_AMO)},
            kind="point",
            geometry={"type": "Point", "coordinates": [56.3, 26.5]},
            label=f"revision {revision}", authority="human_confirmed",
            provenance={"provider": "human", "acquisition": "human"},
            confirmed_by=AMO, supersedes_id=predecessor,
            revision_action="redraw",
        )
        chain_ids.append(predecessor)

    review = await GeoScopeService(world).review(ROOM_AMO, root_id)
    assert review is not None
    assert len(review.lineage) == 505
    assert review.current.id == f"geo_scope:{chain_ids[-1]}"


@pytest.mark.asyncio
async def test_lineage_fails_loudly_when_legacy_rows_contain_a_cycle(world):
    scope_id = await insert_scope(
        world, room_id=ROOM_AMO,
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human"},
        confirmed_by=AMO,
    )
    await world.execute(
        "ALTER TABLE geo_scopes DISABLE TRIGGER geo_scopes_reject_update",
    )
    try:
        await world.execute(
            "UPDATE geo_scopes SET supersedes_id = id WHERE id = $1", scope_id,
        )
    finally:
        await world.execute(
            "ALTER TABLE geo_scopes ENABLE TRIGGER geo_scopes_reject_update",
        )

    with pytest.raises(ValueError, match="cycle"):
        await GeoScopeService(world).review(ROOM_AMO, scope_id)


@pytest.mark.asyncio
async def test_two_independent_review_connections_create_exactly_one_successor_and_event():
    """The row lock and unique successor fence arbitrate a real writer race."""
    schema = f"geo_review_race_{uuid4().hex}"
    setup = await asyncpg.connect(TEST_DATABASE_URL)
    contenders: list[asyncpg.Connection] = []

    async def prepare(conn: asyncpg.Connection) -> None:
        for typename in ("jsonb", "json"):
            await conn.set_type_codec(
                typename, encoder=json.dumps, decoder=json.loads,
                schema="pg_catalog",
            )
        await conn.execute(f'SET search_path TO "{schema}", public')

    try:
        await setup.execute(f'CREATE SCHEMA "{schema}"')
        for table in ("users", "rooms", "room_memberships", "events", "geo_scopes"):
            await setup.execute(
                f'CREATE TABLE "{schema}"."{table}" '
                f'(LIKE public."{table}" INCLUDING ALL)',
            )
        await prepare(setup)
        now = datetime.now(timezone.utc)
        race_user, race_room = uuid4(), uuid4()
        await setup.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, 'Racer')",
            race_user, now,
        )
        await setup.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, 'Race')",
            race_room, now, "race-token",
        )
        await setup.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            race_room, race_user, now,
        )
        proposal_id = await insert_scope(
            setup, room_id=race_room,
            subject={"entity": "rooms", "id": str(race_room)},
            kind="point", geometry={"type": "Point", "coordinates": [56.3, 26.5]},
            authority="machine_proposed",
            provenance={"provider": "llm", "acquisition": "llm"},
            revision_action="propose",
        )

        contenders = [
            await asyncpg.connect(TEST_DATABASE_URL),
            await asyncpg.connect(TEST_DATABASE_URL),
        ]
        for contender in contenders:
            await prepare(contender)
        assert len({conn.get_server_pid() for conn in contenders}) == 2
        barrier = asyncio.Barrier(2)

        async def confirm(conn: asyncpg.Connection) -> object:
            await barrier.wait()
            return await geo_api.confirm_geo_scope(
                race_room, proposal_id, token="race-token",
                current_user=_user(race_user), request=None, db=conn,
            )

        results = await asyncio.gather(
            *(confirm(conn) for conn in contenders), return_exceptions=True,
        )
        winners = [result for result in results if not isinstance(result, BaseException)]
        losers = [result for result in results if isinstance(result, HTTPException)]
        assert len(winners) == 1
        assert [loser.status_code for loser in losers] == [409]
        assert await setup.fetchval(
            "SELECT count(*) FROM geo_scopes WHERE supersedes_id = $1", proposal_id,
        ) == 1
        assert await setup.fetchval(
            "SELECT count(*) FROM events WHERE event_type = 'geo_scope_reviewed'",
        ) == 1
    finally:
        for contender in contenders:
            await contender.close()
        await setup.execute("SET search_path TO public")
        await setup.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await setup.close()


@pytest.mark.asyncio
async def test_revision_event_is_full_fidelity(world):
    scope_id = await _propose(world)
    successor = await geo_api._review(
        ROOM_AMO, scope_id, "reject", _user(AMO), world,
        review_note="wrong basin",
    )
    event = await world.fetchrow(
        """SELECT payload FROM events
           WHERE room_id = $1 AND event_type = 'geo_scope_reviewed'
           ORDER BY timestamp DESC LIMIT 1""",
        ROOM_AMO,
    )
    assert event is not None
    assert event["payload"] == {
        "scope_id": str(scope_id),
        "action": "reject",
        "replacement_id": successor.id.split(":", 1)[1],
        "root_scope_id": str(scope_id),
        "subject": {"entity": "reading_items", "id": str(READING), "field": None},
        "kind": "region",
        "geometry": successor.geometry,
        "label": "Persian Gulf?",
        "authority": "human_confirmed",
        "provenance": {
            "provider": "natural_earth", "acquisition": "llm",
            "source_id": "Persian Gulf", "url": None,
            "credit": "Made with Natural Earth",
        },
        "source_state": "ok",
        "observed_at": None,
        "retrieved_at": successor.retrieved_at.isoformat(),
        "expires_at": None,
        "revision_action": "reject",
        "review_note": "wrong basin",
    }


@pytest.mark.asyncio
async def test_event_failure_rolls_back_the_successor(world, monkeypatch):
    scope_id = await _propose(world)

    async def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event ledger unavailable")

    monkeypatch.setattr(geo_api, "_record_event", fail_event)
    with pytest.raises(RuntimeError, match="event ledger unavailable"):
        await geo_api._review(
            ROOM_AMO, scope_id, "confirm", _user(AMO), world,
        )

    assert await world.fetchval(
        "SELECT count(*) FROM geo_scopes WHERE supersedes_id = $1", scope_id,
    ) == 0
    assert await GeoScopeService(world).is_live(scope_id) is True


@pytest.mark.asyncio
async def test_create_event_failure_rolls_back_the_scope(world, monkeypatch):
    async def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event ledger unavailable")

    monkeypatch.setattr(geo_api, "_record_event", fail_event)
    request = geo_api.GeoScopeCreateRequest(
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        label="atomic",
    )
    with pytest.raises(RuntimeError, match="event ledger unavailable"):
        await geo_api.create_geo_scope(
            ROOM_AMO, request, token=f"tok-{ROOM_AMO}",
            current_user=_user(AMO), db=world,
        )

    assert await world.fetchval(
        "SELECT count(*) FROM geo_scopes WHERE label = 'atomic'",
    ) == 0


@pytest.mark.asyncio
async def test_create_event_contains_the_canonical_persisted_geometry(world):
    request = geo_api.GeoScopeCreateRequest(
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56, 26]},
        label="event geometry",
    )
    scope = await geo_api.create_geo_scope(
        ROOM_AMO, request, token=f"tok-{ROOM_AMO}",
        current_user=_user(AMO), db=world,
    )
    event = await world.fetchrow(
        """SELECT payload FROM events
           WHERE room_id = $1 AND event_type = 'geo_scope_created'
           ORDER BY timestamp DESC LIMIT 1""",
        ROOM_AMO,
    )
    assert event is not None
    assert event["payload"]["geometry"] == scope.geometry


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
async def test_reject_preserves_source_condition_and_hides_both(world):
    sid = await _propose(world)
    replacement = await geo_api._review(ROOM_AMO, sid, "reject", _user(AMO), world)
    assert replacement.source_state == "ok"
    assert replacement.revision_action == "reject"
    assert replacement.review_state == "rejected"
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


# ---------------------------------------------------------------------------
# WorldSignal -> one durable source_reported GeoScope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signal_placement_preserves_server_geometry_provenance_and_event_fidelity(
    world, monkeypatch,
):
    signal = _world_signal("place-1")
    monkeypatch.setattr(geo_api, "world_signal_store", _signal_store(signal))

    scope = await geo_api.place_world_signal(
        ROOM_AMO, signal.id, token=f"tok-{ROOM_AMO}",
        current_user=_user(AMO), db=world,
    )

    assert scope.authority == "source_reported"
    assert scope.revision_action == "place_signal"
    assert scope.created_by == AMO
    assert scope.confirmed_by is None
    assert scope.subject.model_dump() == {
        "entity": "rooms", "id": str(ROOM_AMO), "field": signal.id,
    }
    assert scope.kind == signal.kind
    assert scope.geometry == signal.geometry
    assert scope.label == signal.label
    assert scope.provenance == signal.provenance
    assert scope.source_state == signal.source_state
    assert scope.observed_at == signal.observed_at
    assert scope.retrieved_at == signal.retrieved_at
    assert scope.expires_at == signal.expires_at

    event = await world.fetchrow(
        """SELECT user_id, payload FROM events
           WHERE room_id = $1 AND event_type = $2
             AND payload->>'scope_id' = $3""",
        ROOM_AMO, "geo_scope_created", scope.id.split(":", 1)[1],
    )
    assert event is not None and event["user_id"] == AMO
    assert event["payload"] == {
        "scope_id": scope.id.split(":", 1)[1],
        "subject": scope.subject.model_dump(),
        "kind": signal.kind,
        "geometry": signal.geometry,
        "label": signal.label,
        "authority": "source_reported",
        "provenance": signal.provenance.model_dump(),
        "source_state": "partial",
        "observed_at": signal.observed_at.isoformat(),
        "retrieved_at": signal.retrieved_at.isoformat(),
        "expires_at": signal.expires_at.isoformat(),
        "revision_action": "place_signal",
        "review_note": None,
    }


@pytest.mark.asyncio
async def test_duplicate_signal_placement_replays_one_scope_and_one_event(world, monkeypatch):
    signal = _world_signal("duplicate")
    monkeypatch.setattr(geo_api, "world_signal_store", _signal_store(signal))

    first = await geo_api.place_world_signal(
        ROOM_AMO, signal.id, token=f"tok-{ROOM_AMO}", current_user=_user(AMO), db=world,
    )
    second = await geo_api.place_world_signal(
        ROOM_AMO, signal.id, token=f"tok-{ROOM_AMO}", current_user=_user(AMO), db=world,
    )

    assert second.id == first.id
    assert await world.fetchval(
        """SELECT count(*) FROM geo_scopes
           WHERE room_id = $1 AND subject->>'field' = $2""",
        ROOM_AMO, signal.id,
    ) == 1
    assert await world.fetchval(
        """SELECT count(*) FROM events
           WHERE room_id = $1 AND event_type = 'geo_scope_created'
             AND payload->'subject'->>'field' = $2""",
        ROOM_AMO, signal.id,
    ) == 1


@pytest.mark.asyncio
async def test_two_independent_signal_placements_replay_exactly_one_scope_and_event(
    monkeypatch,
):
    """The advisory lock serializes the real two-connection placement race."""
    schema = f"geo_signal_race_{uuid4().hex}"
    setup = await asyncpg.connect(TEST_DATABASE_URL)
    contenders: list[asyncpg.Connection] = []

    async def prepare(conn: asyncpg.Connection) -> None:
        for typename in ("jsonb", "json"):
            await conn.set_type_codec(
                typename, encoder=json.dumps, decoder=json.loads,
                schema="pg_catalog",
            )
        await conn.execute(f'SET search_path TO "{schema}", public')

    try:
        await setup.execute(f'CREATE SCHEMA "{schema}"')
        for table in ("users", "rooms", "room_memberships", "events", "geo_scopes"):
            await setup.execute(
                f'CREATE TABLE "{schema}"."{table}" '
                f'(LIKE public."{table}" INCLUDING ALL)',
            )
        await prepare(setup)
        now = datetime.now(timezone.utc)
        race_user, race_room = uuid4(), uuid4()
        await setup.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, 'Racer')",
            race_user, now,
        )
        await setup.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, 'Race')",
            race_room, now, "race-token",
        )
        await setup.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            race_room, race_user, now,
        )
        signal = _world_signal("concurrent-place", room_id=race_room)
        monkeypatch.setattr(geo_api, "world_signal_store", _signal_store(signal))

        contenders = [
            await asyncpg.connect(TEST_DATABASE_URL),
            await asyncpg.connect(TEST_DATABASE_URL),
        ]
        for contender in contenders:
            await prepare(contender)
        assert len({conn.get_server_pid() for conn in contenders}) == 2
        barrier = asyncio.Barrier(2)

        async def place(conn: asyncpg.Connection) -> object:
            await barrier.wait()
            return await geo_api.place_world_signal(
                race_room, signal.id, token="race-token",
                current_user=_user(race_user), db=conn,
            )

        results = await asyncio.gather(*(place(conn) for conn in contenders))
        assert results[0].id == results[1].id
        assert await setup.fetchval(
            """SELECT count(*) FROM geo_scopes
               WHERE room_id = $1 AND subject->>'field' = $2""",
            race_room, signal.id,
        ) == 1
        assert await setup.fetchval(
            """SELECT count(*) FROM events
               WHERE room_id = $1 AND event_type = 'geo_scope_created'
                 AND payload->'subject'->>'field' = $2""",
            race_room, signal.id,
        ) == 1
    finally:
        for contender in contenders:
            await contender.close()
        await setup.execute("SET search_path TO public")
        await setup.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await setup.close()


@pytest.mark.asyncio
async def test_signal_placement_copies_the_snapshot_resolved_after_its_lock(
    world, monkeypatch,
):
    old = _world_signal("moves-before-lock")
    replacement_values = old.model_dump()
    replacement_values.update(
        geometry={"type": "Point", "coordinates": [57.1, 25.9]},
        label="Post-lock contact",
        observed_at=old.observed_at + timedelta(seconds=10),
        retrieved_at=old.retrieved_at + timedelta(seconds=10),
    )
    replacement_values["provenance"].update(
        url="https://provider.test/post-lock",
        credit="Post-lock provider credit",
    )
    replacement = WorldSignal(**replacement_values)
    store = _signal_store(old)
    monkeypatch.setattr(geo_api, "world_signal_store", store)
    lock_reached = asyncio.Event()
    allow_lock = asyncio.Event()

    class LockGate:
        def __init__(self, conn: asyncpg.Connection) -> None:
            self._conn = conn

        def __getattr__(self, name: str) -> Any:
            return getattr(self._conn, name)

        async def fetchval(self, query: str, *args: object) -> Any:
            if "pg_advisory_xact_lock" in query:
                lock_reached.set()
                await allow_lock.wait()
            return await self._conn.fetchval(query, *args)

    placement = asyncio.create_task(geo_api.place_world_signal(
        ROOM_AMO, old.id, token=f"tok-{ROOM_AMO}",
        current_user=_user(AMO), db=LockGate(world),
    ))
    await asyncio.wait_for(lock_reached.wait(), timeout=2)
    store.replace(_signal_snapshot(replacement))
    allow_lock.set()
    scope = await asyncio.wait_for(placement, timeout=2)

    assert scope.geometry == replacement.geometry
    assert scope.label == replacement.label
    assert scope.provenance == replacement.provenance
    assert scope.observed_at == replacement.observed_at
    assert scope.retrieved_at == replacement.retrieved_at
    event = await world.fetchrow(
        """SELECT payload FROM events
           WHERE room_id = $1 AND event_type = 'geo_scope_created'
             AND payload->'subject'->>'field' = $2""",
        ROOM_AMO, replacement.id,
    )
    assert event is not None
    assert event["payload"]["geometry"] == replacement.geometry
    assert event["payload"]["label"] == replacement.label
    assert event["payload"]["provenance"] == replacement.provenance.model_dump()


@pytest.mark.asyncio
async def test_signal_placement_failures_leave_no_scope_or_event(world, monkeypatch):
    expired = _world_signal(
        "expired-place", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    cross_room = _world_signal("cross-room", room_id=ROOM_DAN)
    monkeypatch.setattr(geo_api, "world_signal_store", _signal_store(expired, cross_room))
    before_scopes = await world.fetchval("SELECT count(*) FROM geo_scopes")
    before_events = await world.fetchval("SELECT count(*) FROM events")

    cases = (
        ("not-a-signal", 422),
        ("world_signal:ais:missing", 404),
        (cross_room.id, 404),
        (expired.id, 409),
    )
    for signal_id, status in cases:
        with pytest.raises(HTTPException) as exc:
            await geo_api.place_world_signal(
                ROOM_AMO, signal_id, token=f"tok-{ROOM_AMO}",
                current_user=_user(AMO), db=world,
            )
        assert exc.value.status_code == status

    assert await world.fetchval("SELECT count(*) FROM geo_scopes") == before_scopes
    assert await world.fetchval("SELECT count(*) FROM events") == before_events


@pytest.mark.asyncio
async def test_signal_placement_event_failure_rolls_back_the_scope(world, monkeypatch):
    signal = _world_signal("event-failure")
    monkeypatch.setattr(geo_api, "world_signal_store", _signal_store(signal))

    async def fail_event(*args, **kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(geo_api, "_record_event", fail_event)
    before = await world.fetchval("SELECT count(*) FROM geo_scopes")
    with pytest.raises(RuntimeError, match="event write failed"):
        await geo_api.place_world_signal(
            ROOM_AMO, signal.id, token=f"tok-{ROOM_AMO}",
            current_user=_user(AMO), db=world,
        )
    assert await world.fetchval("SELECT count(*) FROM geo_scopes") == before
