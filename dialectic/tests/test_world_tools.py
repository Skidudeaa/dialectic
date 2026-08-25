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
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from field_marks import resolve_subjects_in_room
from geo_scopes import GeoScopeService
from llm import world
from llm.tools import build_registry

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
        linked_book_id = None
        trading_config = None
    tool = build_registry(Room(), None).get("propose_geo_scope")
    assert tool is not None
    assert tool.input_schema["required"] == ["region"]
    assert "never invent coordinates" in tool.description.lower() or "never invent" in tool.description
    monkeypatch.setenv("DIALECTIC_WORLD_ENABLED", "0")
    assert build_registry(Room(), None).get("propose_geo_scope") is None


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
    row = await db.fetchrow("SELECT authority, provenance, expires_at, created_by, subject FROM geo_scopes WHERE id = $1", sid)
    assert row["authority"] == "machine_proposed"
    assert row["provenance"]["acquisition"] == "llm"
    assert row["created_by"] is None
    assert row["expires_at"] is not None
    assert row["subject"] == {"entity": "reading_items", "id": str(READING)}
    # Live (it renders, dashed) — but the Field's allowlist says no.
    assert await GeoScopeService(db).is_live(sid)
    assert await resolve_subjects_in_room(db, ROOM, [{"entity": "geo_scopes", "id": str(sid)}]) is False
    events = await db.fetch("SELECT event_type, payload FROM events WHERE room_id = $1", ROOM)
    assert events[-1]["event_type"] == "geo_scope_created"
    assert events[-1]["payload"]["why"].startswith("tanker")


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
