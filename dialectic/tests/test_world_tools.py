"""
The participant's one World tool (llm/world.py): it resolves names, never
invents coordinates, and what it writes is a proposal the Field refuses
until a person confirms it.

Pure parts run anywhere; the executor runs against real Postgres with
migration 021 (skipped cleanly when absent), because the guard that matters
— "a machine_proposed row cannot anchor a mark" — is a property of SQL.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from field_marks import resolve_subjects_in_room
from geo_scopes import GeoScopeService, insert_scope
from llm import world
from llm.tools import build_registry
from world_signals import (
    WorldSignal,
    WorldSignalSnapshot,
    WorldSignalStore,
)

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-c000-{n:012x}")


AMO, ROOM, READING, OTHER_ROOM, OTHER_READING = _uid(1), _uid(0x11), _uid(0x41), _uid(0x12), _uid(0x42)


# ---------------------------------------------------------------------------
# pure
# ---------------------------------------------------------------------------

def test_natural_earth_resolves_the_gulf_with_provenance():
    name, geometry, provenance = world.natural_earth_region("persian gulf")
    assert name == "Persian Gulf"
    ring = geometry["coordinates"][0]
    assert geometry["type"] == "Polygon" and ring[0] == ring[-1] and len(ring) > 8
    assert provenance["provider"] == "natural_earth"
    assert provenance["acquisition"] == "llm"
    assert provenance["credit"] == "Made with Natural Earth"
    assert provenance["url"].startswith("https://")


def test_an_unknown_name_yields_candidates_not_geometry():
    assert world.natural_earth_region("Strait of Hormuz") is None
    cands = world.candidates_for("Hormuz", ["Strait of Hormuz (approx.)"])
    assert "Strait of Hormuz (approx.)" in cands
    assert world.candidates_for("gulf of omn")[:1] == ["Gulf of Oman"]
    assert len(world.candidates_for("zzzz")) <= 5


def test_the_tool_is_registered_and_shaped(monkeypatch):
    class Room:
        id = ROOM
        name = "Hormuz room"
        linked_book_id = None
        trading_config = None
    tool = build_registry(Room(), None).get("propose_geo_scope")
    assert tool is not None
    assert tool.input_schema["required"] == ["region"]
    assert "never invent coordinates" in tool.description.lower() or "never invent" in tool.description
    query = build_registry(Room(), None).get("world_query")
    assert query is not None
    assert query.input_schema["required"] == []
    assert "read-only" in query.description.lower()
    assert query.label == "reading the world"
    assert query.timeout_s > world.WORLD_QUERY_INNER_TIMEOUT_S
    monkeypatch.setenv("DIALECTIC_WORLD_ENABLED", "0")
    assert build_registry(Room(), None).get("propose_geo_scope") is None
    assert build_registry(Room(), None).get("world_query") is None


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
        await conn.set_type_codec(typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    if not await conn.fetchval("SELECT to_regclass('geo_scopes')"):
        await conn.close()
        pytest.skip("migration 021 not applied to the test database")
        return
    tx = conn.transaction()
    await tx.start()
    now = datetime.now(timezone.utc)
    await db_seed(conn, now)
    yield conn
    await tx.rollback()
    await conn.close()


async def db_seed(conn, now):
    await conn.execute("INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo')", AMO, now)
    for rid in (ROOM, OTHER_ROOM):
        await conn.execute("INSERT INTO rooms (id, name, token, created_at) VALUES ($1,'r',$2,$3)", rid, f"tok-{rid}", now)
    await conn.execute("INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)", ROOM, AMO, now)
    for rid, rd, url in ((ROOM, READING, "https://example.test/tankers"), (OTHER_ROOM, OTHER_READING, "https://example.test/elsewhere")):
        await conn.execute(
            """INSERT INTO reading_items (id, room_id, url, title, site, content, summary, source, created_at)
               VALUES ($1,$2,$3,'t','example.test','b','s','wire',$4)""", rd, rid, url, now,
        )


@pytest.mark.asyncio
async def test_a_proposal_is_provisional_and_the_field_refuses_it(db):
    out = await world.propose_geo_scope(db, ROOM, {
        "region": "Persian Gulf", "subject_kind": "reading",
        "reading_url": "https://example.test/tankers", "why": "tanker counts are about the Gulf",
    })
    assert out["ok"] is True and out["authority"] == "machine_proposed"
    sid = UUID(out["scope_id"])
    row = await db.fetchrow(
        """SELECT authority, geometry, provenance, retrieved_at, expires_at,
                  created_by, subject, revision_action
           FROM geo_scopes WHERE id = $1""",
        sid,
    )
    assert row["authority"] == "machine_proposed"
    assert row["provenance"]["acquisition"] == "llm"
    assert row["created_by"] is None
    assert row["expires_at"] is not None
    assert row["revision_action"] == "propose"
    assert row["subject"] == {"entity": "reading_items", "id": str(READING)}
    # Live (it renders, dashed) — but the Field's allowlist says no.
    assert await GeoScopeService(db).is_live(sid)
    assert await resolve_subjects_in_room(db, ROOM, [{"entity": "geo_scopes", "id": str(sid)}]) is False
    events = await db.fetch("SELECT event_type, payload FROM events WHERE room_id = $1", ROOM)
    assert events[-1]["event_type"] == "geo_scope_created"
    assert events[-1]["payload"] == {
        "scope_id": str(sid),
        "kind": "region",
        "subject": {"entity": "reading_items", "id": str(READING)},
        "label": "Persian Gulf",
        "geometry": row["geometry"],
        "authority": "machine_proposed",
        "provenance": row["provenance"],
        "source_state": "ok",
        "observed_at": None,
        "retrieved_at": row["retrieved_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "revision_action": "propose",
        "review_note": None,
        "why": "tanker counts are about the Gulf",
    }


@pytest.mark.asyncio
async def test_proposal_event_failure_rolls_back_the_scope(db, monkeypatch):
    async def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event ledger unavailable")

    monkeypatch.setattr(world, "_record_event", fail_event, raising=False)
    with pytest.raises(RuntimeError, match="event ledger unavailable"):
        await world.propose_geo_scope(db, ROOM, {"region": "Persian Gulf"})

    assert await db.fetchval(
        "SELECT count(*) FROM geo_scopes WHERE room_id = $1", ROOM,
    ) == 0


@pytest.mark.asyncio
async def test_it_prefers_the_rooms_own_confirmed_scope_by_label(db):
    from geo_scopes import insert_scope
    ring = [[55.6, 26.0], [56.2, 25.6], [57.2, 25.9], [55.6, 26.0]]
    await insert_scope(
        db, room_id=ROOM, subject={"entity": "rooms", "id": str(ROOM)}, kind="polygon",
        geometry={"type": "Polygon", "coordinates": [ring]}, label="Strait of Hormuz (approx.)",
        authority="human_confirmed", provenance={"provider": "human", "acquisition": "human", "credit": "sketch"},
        confirmed_by=AMO,
    )
    out = await world.propose_geo_scope(db, ROOM, {"region": "strait of hormuz (approx.)"})
    assert out["ok"] is True and out["label"] == "Strait of Hormuz (approx.)"
    row = await db.fetchrow("SELECT kind, geometry, provenance FROM geo_scopes WHERE id = $1", UUID(out["scope_id"]))
    assert row["kind"] == "polygon"
    assert row["geometry"]["coordinates"][0] == ring
    assert row["provenance"]["provider"] == "room_scope" and row["provenance"]["credit"] == "sketch"


@pytest.mark.asyncio
async def test_it_never_guesses(db):
    miss = await world.propose_geo_scope(db, ROOM, {"region": "Hormuz"})
    assert miss["ok"] is False and miss["candidates"]
    assert await db.fetchval("SELECT count(*) FROM geo_scopes WHERE room_id = $1", ROOM) == 0
    foreign = await world.propose_geo_scope(db, ROOM, {
        "region": "Persian Gulf", "subject_kind": "reading", "subject_id": str(OTHER_READING),
    })
    assert foreign["ok"] is False and "not in this room" in foreign["error"]
    with pytest.raises(ValueError):
        await world.propose_geo_scope(db, ROOM, {"region": ""})
    with pytest.raises(ValueError):
        await world.propose_geo_scope(db, ROOM, {"region": "Red Sea", "subject_kind": "reading", "subject_id": "nope"})


async def _accepted_scope(db, *, label: str, subject: dict | None = None) -> UUID:
    return await insert_scope(
        db,
        room_id=ROOM,
        subject=subject or {"entity": "rooms", "id": str(ROOM)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        label=label,
        authority="human_confirmed",
        provenance={
            "provider": "human",
            "acquisition": "human",
            "source_id": "inspection",
            "credit": "Amo",
        },
        confirmed_by=AMO,
        revision_action="place",
        created_by=AMO,
    )


@pytest.mark.asyncio
async def test_world_query_resolves_exact_canonical_id_and_exact_label(db):
    scope_id = await _accepted_scope(db, label="Strait of Hormuz (approx.)")

    by_id = await world.world_query(db, ROOM, "Hormuz room", {"scope": f"geo_scope:{scope_id}"})
    by_label = await world.world_query(db, ROOM, "Hormuz room", {"scope": "Strait of Hormuz (approx.)"})

    assert by_id["ok"] is True
    assert by_id["scope"] == by_label["scope"]
    assert by_id["room"] == {"id": str(ROOM), "label": "Hormuz room"}
    assert by_id["scope"]["id"] == f"geo_scope:{scope_id}"
    assert by_id["scope"]["authority"] == "human_confirmed"
    assert by_id["scope"]["review_state"] == "accepted"
    assert by_id["scope"]["source_state"] == "ok"
    assert by_id["scope"]["freshness"]["state"] == "not_applicable"
    assert by_id["show_on_world"] == {
        "room_id": str(ROOM), "scene": "atlas", "view": f"world;room={ROOM}",
    }


@pytest.mark.asyncio
async def test_world_query_exact_lookup_is_deterministic_for_ambiguous_and_missing(db):
    first = await _accepted_scope(db, label="Duplicate")
    second = await _accepted_scope(db, label="Duplicate")

    ambiguous = await world.world_query(db, ROOM, "Hormuz room", {"scope": "Duplicate"})
    wrong_case = await world.world_query(db, ROOM, "Hormuz room", {"scope": "duplicate"})
    malformed = await world.world_query(db, ROOM, "Hormuz room", {"scope": "geo_scope:not-a-uuid"})

    assert ambiguous == {
        "ok": False,
        "error": "ambiguous_scope_label",
        "scope": "Duplicate",
        "matches": sorted([f"geo_scope:{first}", f"geo_scope:{second}"]),
    }
    assert wrong_case["error"] == "scope_not_found"
    assert malformed["error"] == "scope_not_found"


@pytest.mark.asyncio
async def test_world_query_reports_causal_roles_provisional_language_and_bounded_lineage(db):
    scope_id = await _accepted_scope(db, label="Hormuz evidence")
    subjects = [
        {"entity": "rooms", "id": str(ROOM), "field": "thesis_node:hormuz-book:shipping"},
        {"entity": "geo_scopes", "id": str(scope_id)},
    ]
    mark_id = uuid4()
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, mark_kind, relation, origin, provenance, subjects,
                title, payload, actor_user_id, dedup_key)
           VALUES ($1,$2,'relation','supports','explicit','human',$3,$4,$5,$6,$7)""",
        mark_id, ROOM, subjects, "Shipping chokepoint", {
            "node_label": "Shipping chokepoint", "scope_label": "Hormuz evidence",
        }, AMO, f"supports|geo_scopes:{scope_id},rooms:{ROOM}#thesis_node:hormuz-book:shipping",
    )

    out = await world.world_query(db, ROOM, "Hormuz room", {"scope": "Hormuz evidence"})

    assert out["scope"]["lineage"]["total"] == 1
    assert out["scope"]["lineage"]["omitted"] == 0
    assert out["scope"]["causal_bindings"] == [{
        "id": f"field_mark:{mark_id}",
        "relation": "supports",
        "review_state": "provisional",
        "provisional": True,
        "evidence_scope_id": str(scope_id),
        "target": {
            "room_id": str(ROOM),
            "book_id": "hormuz-book",
            "node_id": "shipping",
            "node_label": "Shipping chokepoint",
        },
    }]
    assert "human review" in out["scope"]["causal_note"].lower()


def _signal(now: datetime, *, source_id: str = "one") -> WorldSignal:
    return WorldSignal(
        id=f"world_signal:test_provider:{source_id}",
        provider="test_provider",
        source_id=source_id,
        room_id=ROOM,
        layer="vessel",
        kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        provenance={
            "provider": "test_provider", "acquisition": "adapter:test_provider",
            "source_id": source_id, "credit": "Synthetic isolated test",
        },
        source_state="ok",
        freshness="current",
        coverage="1 synthetic observation",
        observed_at=now,
        retrieved_at=now,
        expires_at=now + timedelta(hours=1),
        label="Synthetic vessel",
    )


@pytest.mark.asyncio
async def test_world_query_signal_states_keep_unknown_and_unavailable_distinct_from_zero(db):
    now = datetime.now(timezone.utc)
    not_configured = await world.world_query(
        db, ROOM, "Hormuz room", {}, signal_store=WorldSignalStore(), now=now,
    )
    assert not_configured["signals"] == {
        "status": "not_configured", "current_signal_count": None,
        "sources": [], "items": [], "omitted": 0,
    }

    store = WorldSignalStore()
    store.replace(WorldSignalSnapshot(
        provider="empty_provider", configured_room_ids=frozenset({ROOM}),
        source_state="ok", freshness="current", coverage="complete empty window",
        observed_at=now, retrieved_at=now, signals=(),
    ))
    store.replace(WorldSignalSnapshot(
        provider="unknown_provider", configured_room_ids=frozenset({ROOM}),
        source_state="stale", freshness="unknown", coverage="unknown",
        observed_at=None, retrieved_at=now, signals=(),
    ))
    store.replace(WorldSignalSnapshot(
        provider="down_provider", configured_room_ids=frozenset({ROOM}),
        source_state="unavailable", freshness="unknown", coverage="poll failed",
        observed_at=None, retrieved_at=now, signals=(),
    ))
    out = await world.world_query(db, ROOM, "Hormuz room", {}, signal_store=store, now=now)
    by_provider = {source["provider"]: source for source in out["signals"]["sources"]}
    assert by_provider["empty_provider"]["status"] == "empty"
    assert by_provider["empty_provider"]["current_signal_count"] == 0
    assert by_provider["unknown_provider"]["status"] == "unknown"
    assert by_provider["unknown_provider"]["current_signal_count"] is None
    assert by_provider["down_provider"]["status"] == "unavailable"
    assert by_provider["down_provider"]["current_signal_count"] is None
    assert out["signals"]["current_signal_count"] is None


@pytest.mark.asyncio
async def test_world_query_fences_other_rooms_and_never_calls_write_methods(db):
    own = await _accepted_scope(db, label="Own")
    await insert_scope(
        db, room_id=OTHER_ROOM,
        subject={"entity": "rooms", "id": str(OTHER_ROOM)}, kind="point",
        geometry={"type": "Point", "coordinates": [1, 1]}, label="Foreign secret",
        authority="source_reported",
        provenance={"provider": "secret", "acquisition": "adapter:secret", "credit": "secret"},
        revision_action="place_signal",
    )
    before = (
        await db.fetchval("SELECT count(*) FROM geo_scopes"),
        await db.fetchval("SELECT count(*) FROM field_marks"),
        await db.fetchval("SELECT count(*) FROM events"),
    )

    listing = await world.world_query(db, ROOM, "Hormuz room", {})
    foreign = await world.world_query(db, ROOM, "Hormuz room", {"scope": "Foreign secret"})
    after = (
        await db.fetchval("SELECT count(*) FROM geo_scopes"),
        await db.fetchval("SELECT count(*) FROM field_marks"),
        await db.fetchval("SELECT count(*) FROM events"),
    )

    assert [item["id"] for item in listing["scopes"]["items"]] == [f"geo_scope:{own}"]
    assert "Foreign secret" not in json.dumps(listing)
    assert foreign["error"] == "scope_not_found"
    assert after == before
