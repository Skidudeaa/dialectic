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


@pytest.mark.asyncio
class TestEmptyRoom:
    async def test_empty_room_renders_nothing(self, db):
        record = await build_room_record(db, ROOM)
        assert record.to_prompt_section() == ""
