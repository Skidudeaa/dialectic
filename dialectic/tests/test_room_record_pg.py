"""Tests for room_record.py — the participant's own read model over what a
room has already recorded (the Field, commitments, the Round, readings).

WHY real Postgres: `build_room_record` composes FieldMarkService,
`_correction_digest_rows` (llm/field_inference.py), a direct Round SQL
statement, and WorkspaceObjectService — the property that matters most
(the Round line never carries a forecast VALUE) is a property of query
TEXT, not of Python, and only a real query proves it. Fixture idiom
copied from tests/test_field_inference.py and tests/test_rounds_pg.py.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from room_record import build_room_record

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0x9901)
DAN = _uid(0x9902)
ROOM = _uid(0x9911)
THREAD = _uid(0x9921)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
        return
    import json
    for kind in ("jsonb", "json"):
        await conn.set_type_codec(
            kind, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES "
            "($1, now(), 'Amo'), ($2, now(), 'Dan')", AMO, DAN,
        )
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) VALUES "
            "($1, now(), 'Record Room', 'room-record-test-token')", ROOM,
        )
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES "
            "($1, $2, now(), 'Main')", THREAD, ROOM,
        )
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


async def _mark(db, *, origin="inferred", relation="emerging_position",
                 title="A position", provenance="field_inference") -> UUID:
    mid = uuid4()
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                title, provenance, created_at)
           VALUES ($1, $2, $3, 'relation', $4, $5, $6, $7, now())""",
        mid, ROOM, THREAD, relation, origin, title, provenance,
    )
    return mid


async def _confirm(db, mark_id: UUID, actor: UUID = AMO) -> None:
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, action, target_mark_id,
                actor_user_id, provenance, created_at)
           VALUES ($1, $2, $3, 'review', 'confirm', $4, $5, 'human', now())""",
        uuid4(), ROOM, THREAD, mark_id, actor,
    )


async def _round_question(db, *, claim: str = "Does the BOJ raise?",
                           closes_in_days: int = 5) -> UUID:
    qid = uuid4()
    await db.execute(
        """INSERT INTO commitments
               (id, room_id, thread_id, claim, resolution_criteria, category,
                created_at, deadline, status)
           VALUES ($1, $2, $3, $4, 'Resolves on the statement.', 'round',
                   now(), $5, 'active')""",
        qid, ROOM, THREAD, claim,
        datetime.now(timezone.utc) + timedelta(days=closes_in_days),
    )
    return qid


@pytest.mark.asyncio
class TestFieldMarks:
    async def test_provisional_excluded_confirmed_included(self, db):
        await _mark(db, title="Provisional draft")
        confirmed_id = await _mark(db, title="Confirmed claim")
        await _confirm(db, confirmed_id)

        record = await build_room_record(db, ROOM)
        text = record.to_prompt_section()

        assert "Confirmed claim" in text
        assert "(confirmed)" in text
        assert "Provisional draft" not in text


@pytest.mark.asyncio
class TestRoundBlindness:
    async def test_presence_only_no_confidence_leaks(self, db):
        """MUTATION GUARD: this is the test that must fail if room_record's
        `_ROUND_SQL` is ever changed to select (and someone then renders)
        `cc.confidence` or `cc.peer_forecast`. The Round's entire reason to
        exist is that a forecast's number stays sealed until BOTH humans
        commit (stakes/house.py) — and this read model has no viewer to
        gate on at all, so it must never see the number in the first
        place. Both the exact value "0.37" and its bare digits "37" are
        asserted absent.
        """
        await _round_question(db)
        qid = await _round_question(db, claim="Does USDJPY break 160?")
        await db.execute(
            """INSERT INTO commitment_confidence
                   (commitment_id, user_id, confidence, actor)
               VALUES ($1, $2, 0.37, 'human')""",
            qid, AMO,
        )

        record = await build_room_record(db, ROOM)
        text = record.to_prompt_section()

        assert "Does USDJPY break 160?" in text
        assert "1 of 2 humans" in text
        assert "0.37" not in text
        assert "37" not in text


async def _scope(db, *, label: str, confirmed_by: UUID = AMO,
                  authority: str = "human_confirmed") -> UUID:
    from geo_scopes import insert_scope
    ring = [[55.6, 26.0], [56.2, 25.6], [57.2, 25.9], [55.6, 26.0]]
    acquisition = "llm" if authority == "machine_proposed" else "human"
    return await insert_scope(
        db, room_id=ROOM, subject={"entity": "rooms", "id": str(ROOM)},
        kind="polygon", geometry={"type": "Polygon", "coordinates": [ring]},
        label=label, authority=authority,
        provenance={"provider": "human", "acquisition": acquisition, "credit": "sketch"},
        confirmed_by=confirmed_by if authority == "human_confirmed" else None,
    )


async def _causal_mark(db, *, scope_id: UUID, node_id: str = "hormuz",
                        relation: str = "supports") -> None:
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                title, provenance, subjects, created_at)
           VALUES ($1, $2, $3, 'relation', $4, 'explicit', 'evidence',
                   'human', $5, now())""",
        uuid4(), ROOM, THREAD, relation,
        [
            {"entity": "geo_scopes", "id": str(scope_id)},
            {"entity": "rooms", "id": str(ROOM), "field": f"thesis_node:book-1:{node_id}"},
        ],
    )


async def _observation(db, *, scope_id: UUID, label: str, provider: str = "adsb",
                        layer: str = "aircraft", lon: float = 56.301234,
                        lat: float = 26.501234, seen_count: int = 1) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        """INSERT INTO world_observations
               (id, room_id, scope_id, provider, signal_id, layer, kind, label,
                geometry, provenance, details, observed_at, retrieved_at,
                first_seen_at, last_seen_at, seen_count)
           VALUES ($1, $2, $3, $4, $5, $6, 'point', $7, $8, $9, '{}', $10, $10,
                   $10, $10, $11)""",
        uuid4(), ROOM, scope_id, provider, f"world_signal:{provider}:{label}",
        layer, label,
        {"type": "Point", "coordinates": [lon, lat]},
        {"provider": provider, "acquisition": "adapter", "credit": "test"},
        now, seen_count,
    )


@pytest.mark.asyncio
class TestGeography:
    async def test_bound_scope_renders_relation_and_node(self, db):
        scope_id = await _scope(db, label="Strait of Hormuz (approx.)")
        await _causal_mark(db, scope_id=scope_id, node_id="hormuz-node")

        record = await build_room_record(db, ROOM)
        text = record.to_prompt_section()

        assert "### Geography" in text
        assert "Strait of Hormuz (approx.)" in text
        assert "→ supports hormuz-node" in text

    async def test_unbound_scope_renders_unbound(self, db):
        await _scope(db, label="Persian Gulf")

        record = await build_room_record(db, ROOM)
        text = record.to_prompt_section()

        assert "Persian Gulf" in text
        assert "— unbound" in text

    async def test_machine_proposed_scope_excluded(self, db):
        await _scope(db, label="Guessed Region", authority="machine_proposed")

        record = await build_room_record(db, ROOM)

        assert record.geography_lines == []


@pytest.mark.asyncio
class TestSeenInTheWorld:
    async def test_observation_row_renders_with_no_coordinates(self, db):
        scope_id = await _scope(db, label="Strait of Hormuz (approx.)")
        await _causal_mark(db, scope_id=scope_id, node_id="hormuz-node")
        await _observation(
            db, scope_id=scope_id, label="Tanker 1", lon=56.301234, lat=26.501234,
        )

        record = await build_room_record(db, ROOM)
        text = record.to_prompt_section()

        assert "### Seen in the world (24h)" in text
        assert "Strait of Hormuz (approx.)" in text
        assert "aircraft contact" in text
        assert "Tanker 1" in text
        # Coordinates never leak: neither the raw geometry digits nor the
        # digits appear anywhere in the rendered section.
        assert "56.301234" not in text
        assert "26.501234" not in text
        assert "56301234" not in text
        assert "26501234" not in text

    async def test_fires_line_counts_new_cells_against_the_baseline(self, db):
        scope_id = await _scope(db, label="Persian Gulf")
        await _observation(db, scope_id=scope_id, label="Fire · 30 MW · high conf · NEW vs 30-day baseline",
                           provider="firms", layer="fires")
        await db.execute(
            "UPDATE world_observations SET details = '{\"novel\": true}' WHERE layer='fires'")
        for n in range(2):
            await _observation(db, scope_id=scope_id, label=f"Fire · 9 MW · nominal conf · recurring {n+1}d (likely flare)",
                               provider="firms", layer="fires", lon=50.1 + n)
        await db.execute(
            "UPDATE world_observations SET details = '{\"novel\": false}' WHERE layer='fires' AND details = '{}'")

        text = (await build_room_record(db, ROOM)).to_prompt_section()

        assert "Persian Gulf: 3 fires contact(s), 1 NEW vs 30-day baseline" in text
        assert "NASA FIRMS" in text  # the header explains what a fires contact is

    async def test_empty_observations_render_no_block(self, db):
        await _scope(db, label="Persian Gulf")

        record = await build_room_record(db, ROOM)

        assert record.world_lines == []
        assert "Seen in the world" not in record.to_prompt_section()


@pytest.mark.asyncio
class TestEmptyRoom:
    async def test_empty_room_renders_nothing(self, db):
        record = await build_room_record(db, ROOM)
        assert record.to_prompt_section() == ""
