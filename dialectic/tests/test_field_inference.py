"""
Tests for llm/field_inference.py — the half-hourly job that pencils in
provisional Field structure.

WHY real Postgres: the guarantees that matter here (the dedup index, the
caps counted FROM field_marks rows, the room fence on subject resolution)
are properties of the real table, not of Python alone — mirroring
tests/test_field_marks_pg.py and tests/test_reading_echo.py's own reasoning
("the job spends LLM money on a wall-clock timer... the expensive mistakes
are echoing twice"). ONLY the LLM call itself is mocked (`_generate_candidates`
monkeypatched), matching the plan's "template: reading_echo's tests; provider
mocked".
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from field_marks import compute_dedup_key
from geo_scopes import insert_scope
from llm import field_inference
from scheduler import Scheduler, SchedulerContext

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xFB01)
ROOM = _uid(0xFB11)
FOREIGN_ROOM = _uid(0xFB12)
TH = _uid(0xFB21)
FOREIGN_TH = _uid(0xFB22)
MSG_A = _uid(0xFB31)
MSG_B = _uid(0xFB32)
FOREIGN_MSG = _uid(0xFB33)

BASE = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


class _FakePool:
    """Wraps one real asyncpg connection so field_inference.run() (which does
    `async with ctx.pool.acquire() as conn:`) can drive it directly."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    import json
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def inference_room(db):
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo')",
        AMO, _d(40))
    for rid, nm in ((ROOM, "Inference Room"), (FOREIGN_ROOM, "Foreign Room")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, _d(30), f"inference-{rid}", nm)
    for tid, rid in ((TH, ROOM), (FOREIGN_TH, FOREIGN_ROOM)):
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            tid, rid, _d(30))
    # Migration 013 bootstraps exactly one is_home room and a partial unique
    # index enforces the singleton — reuse it rather than creating a second.
    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    home_thread = await db.fetchval(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        home_id,
    )
    if home_thread is None:
        home_thread = uuid4()
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            home_thread, home_id, _d(30))

    now = datetime.now(timezone.utc)
    for mid, tid, seq, at in (
        (MSG_A, TH, 1, now - timedelta(minutes=30)),
        (MSG_B, TH, 2, now - timedelta(minutes=10)),
    ):
        await db.execute(
            """INSERT INTO messages (id,thread_id,sequence,created_at,speaker_type,
                   user_id,message_type,content,is_deleted)
               VALUES ($1,$2,$3,$4,'human',$5,'text','the strait might close',false)""",
            mid, tid, seq, at, AMO)
    await db.execute(
        """INSERT INTO messages (id,thread_id,sequence,created_at,speaker_type,
               user_id,message_type,content,is_deleted)
           VALUES ($1,$2,1,$3,'human',$4,'text','foreign room content',false)""",
        FOREIGN_MSG, FOREIGN_TH, now - timedelta(minutes=20), AMO)
    await db.execute(
        """INSERT INTO messages (id,thread_id,sequence,created_at,speaker_type,
               user_id,message_type,content,is_deleted)
           VALUES ($1,$2,
               (SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE thread_id=$2),
               $3,'human',$4,'text','home content',false)""",
        uuid4(), home_thread, now - timedelta(minutes=20), AMO)
    yield db
    await tx.rollback()


def _candidate(relation="emerging_position", subjects=None, title="A position"):
    return {
        "relation": relation,
        "subjects": subjects or [{"entity": "messages", "id": str(MSG_A)}],
        "title": title,
        "quote": "the strait might close",
    }


async def _inserted_rows(db, room_id):
    return await db.fetch(
        "SELECT relation, subjects, dedup_key FROM field_marks "
        "WHERE room_id = $1 AND provenance = 'field_inference'", room_id,
    )


# ---------------------------------------------------------------------------
# kill switch
# ---------------------------------------------------------------------------

def test_kill_switch_honored(monkeypatch):
    scheduler = Scheduler(SchedulerContext(pool=None))
    field_inference.register_field_inference_jobs(scheduler)
    jobs = [j for j in scheduler.jobs if j.name == "field_inference"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.enabled_env == "FIELD_INFERENCE_ENABLED"

    monkeypatch.delenv("FIELD_INFERENCE_ENABLED", raising=False)
    assert job.enabled() is True, "default ON when unset"

    monkeypatch.setenv("FIELD_INFERENCE_ENABLED", "0")
    assert job.enabled() is False


# ---------------------------------------------------------------------------
# the cheap gate — no LLM spend on a quiet room
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_new_messages_gate_spends_no_llm_call(inference_room, monkeypatch):
    # A mark newer than every message in the room: nothing is "new" relative
    # to it, so the gate must skip before ever calling the model.
    await inference_room.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, created_at, dedup_key)
           VALUES ($1,$2,$3,'relation','emerging_position','inferred',
                   'field_inference',$4,'already covered',$5,$6)""",
        uuid4(), ROOM, TH, [{"entity": "messages", "id": str(MSG_B)}],
        datetime.now(timezone.utc), compute_dedup_key(
            "emerging_position", [{"entity": "messages", "id": str(MSG_B)}]),
    )

    # FOREIGN_ROOM is a second legitimately-active room in this fixture and
    # SHOULD still get its own call — the gate is per-room. So the assertion
    # below is scoped to ROOM's own thread, not a global call count.
    called_threads = []

    async def _spy(messages, active_marks, digest_rows, **kwargs):
        called_threads.append(messages[0]["thread_id"] if messages else None)
        return [_candidate()]

    monkeypatch.setattr(field_inference, "_generate_candidates", _spy)

    detail = await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    assert TH not in called_threads, "the LLM must not be called once the gate skips"
    room_skips = [s for s in detail["skipped"] if s["room"] == str(ROOM)]
    assert room_skips and room_skips[0]["reason"] == "no_new_content"


# ---------------------------------------------------------------------------
# Home is never a candidate room
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_home_room_is_never_a_candidate(inference_room):
    home_id = await inference_room.fetchval("SELECT id FROM rooms WHERE is_home")
    assert home_id is not None, "no Home room in the test database"

    active = await field_inference._active_rooms(inference_room)
    active_ids = {row["id"] for row in active}

    assert ROOM in active_ids, "the fixture's own active room must be a candidate"
    assert home_id not in active_ids, "Home holds no Field -- never a candidate room"


# ---------------------------------------------------------------------------
# hard validation — invalid relation / foreign-room subject dropped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_relation_is_dropped(inference_room, monkeypatch):
    async def _fake(*args, **kwargs):
        return [_candidate(relation="not_a_real_relation")]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    rows = await _inserted_rows(inference_room, ROOM)
    assert rows == []


@pytest.mark.asyncio
async def test_a_foreign_room_subject_is_dropped(inference_room, monkeypatch):
    async def _fake(*args, **kwargs):
        return [_candidate(subjects=[{"entity": "messages", "id": str(FOREIGN_MSG)}])]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    rows = await _inserted_rows(inference_room, ROOM)
    assert rows == [], "a subject naming another room's message must never mint provenance"


@pytest.mark.asyncio
async def test_inference_cannot_bypass_the_causal_structure_bridge(
    inference_room, monkeypatch,
):
    """Only api.field owns the authenticated room/book/node proof.

    Even a model candidate whose GeoScope is genuinely accepted and live must
    not use the lower-level subject resolver to insert a causal room target.
    """
    scope_id = await insert_scope(
        inference_room,
        room_id=ROOM,
        subject={"entity": "messages", "id": str(MSG_A)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.25, 26.55]},
        label="Hormuz evidence",
        authority="source_reported",
        provenance={"provider": "test", "acquisition": "adapter:test"},
    )
    candidate = _candidate(
        relation="supports",
        subjects=[
            {"entity": "geo_scopes", "id": str(scope_id)},
            {
                "entity": "rooms",
                "id": str(ROOM),
                "field": "thesis_node:unverified-book:unverified-node",
            },
        ],
    )

    async def _fake(*args, **kwargs):
        return [candidate]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    assert await _inserted_rows(inference_room, ROOM) == []
    assert await inference_room.fetchval(
        "SELECT count(*) FROM events WHERE room_id = $1 "
        "AND event_type = 'field_mark_inferred'", ROOM,
    ) == 0


@pytest.mark.asyncio
async def test_a_valid_candidate_is_inserted(inference_room, monkeypatch):
    async def _fake(*args, **kwargs):
        return [_candidate()]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    detail = await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    rows = await _inserted_rows(inference_room, ROOM)
    assert len(rows) == 1
    processed = [p for p in detail["processed"] if p["room"] == str(ROOM)]
    assert processed and processed[0]["inserted"] == 1

    event = await inference_room.fetchrow(
        "SELECT payload FROM events WHERE event_type = 'field_mark_inferred' "
        "AND room_id = $1", ROOM,
    )
    assert event is not None


# ---------------------------------------------------------------------------
# caps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_room_cap_is_honored(inference_room, monkeypatch):
    candidates = [
        _candidate(subjects=[{"entity": "messages", "id": str(MSG_A)}],
                  title=f"candidate {i}", relation="unanswered_question")
        for i in range(field_inference.FIELD_INFERENCE_ROOM_CAP + 5)
    ]
    # Each candidate must be individually valid AND distinct (different
    # payload alone does not change the dedup_key -- only relation+subjects
    # do), so give each a unique subject to avoid colliding with itself.
    for i, c in enumerate(candidates):
        c["subjects"] = [{"entity": "messages", "id": str(MSG_A), "field": f"slot{i}"}]

    async def _fake(*args, **kwargs):
        return candidates

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    rows = await _inserted_rows(inference_room, ROOM)
    assert len(rows) == field_inference.FIELD_INFERENCE_ROOM_CAP


@pytest.mark.asyncio
async def test_daily_cap_skips_before_any_llm_call(inference_room, monkeypatch):
    # Anchor inside the current UTC day even during its first hour. The old
    # `now - 1 hour` crossed into yesterday from 00:00–00:59 UTC and made the
    # test deterministic red despite inserting FIELD_INFERENCE_DAILY_CAP rows.
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    # Keep a message after the cap rows so the fresh-content gate cannot be the
    # reason this room skips; this assertion is specifically about daily_cap.
    await inference_room.execute(
        "UPDATE messages SET created_at = $1 WHERE id = $2",
        today + timedelta(microseconds=1), MSG_B,
    )
    for i in range(field_inference.FIELD_INFERENCE_DAILY_CAP):
        await inference_room.execute(
            """INSERT INTO field_marks
                   (id, room_id, thread_id, mark_kind, relation, origin,
                    provenance, subjects, title, created_at, dedup_key)
               VALUES ($1,$2,$3,'relation','unanswered_question','inferred',
                       'field_inference',$4,$5,$6,$7)""",
            uuid4(), ROOM, TH,
            [{"entity": "messages", "id": str(MSG_A), "field": f"cap{i}"}],
            f"cap filler {i}", today,
            compute_dedup_key("unanswered_question",
                              [{"entity": "messages", "id": str(MSG_A), "field": f"cap{i}"}]),
        )

    called_threads = []

    async def _spy(messages, active_marks, digest_rows, **kwargs):
        called_threads.append(messages[0]["thread_id"] if messages else None)
        return [_candidate()]

    monkeypatch.setattr(field_inference, "_generate_candidates", _spy)
    detail = await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    assert TH not in called_threads
    room_skips = [s for s in detail["skipped"] if s["room"] == str(ROOM)]
    assert room_skips and room_skips[0]["reason"] == "daily_cap"


# ---------------------------------------------------------------------------
# §14.5 — a contested mark's identical candidate is never re-inserted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_14_5_guarantee_contest_then_identical_candidate_zero_inserts(
    inference_room, monkeypatch,
):
    relation = "possible_contradiction"
    subjects = [{"entity": "messages", "id": str(MSG_A)}]
    mark_id = uuid4()
    await inference_room.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, created_at, dedup_key)
           VALUES ($1,$2,$3,'relation',$4,'inferred','field_inference',
                   $5,'a contested claim',$6,$7)""",
        mark_id, ROOM, TH, relation, subjects,
        datetime.now(timezone.utc) - timedelta(days=1),
        compute_dedup_key(relation, subjects),
    )
    # A human contests it.
    await inference_room.execute(
        """INSERT INTO field_marks
               (id, room_id, mark_kind, action, target_mark_id, actor_user_id,
                provenance, created_at, payload)
           VALUES ($1,$2,'review','contest',$3,$4,'human',$5,'{}')""",
        uuid4(), ROOM, mark_id, AMO, datetime.now(timezone.utc),
    )

    before = await _inserted_rows(inference_room, ROOM)
    assert len(before) == 1

    async def _fake(*args, **kwargs):
        # The model proposes the IDENTICAL candidate again.
        return [_candidate(relation=relation, subjects=subjects,
                           title="a contested claim (again)")]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    after = await _inserted_rows(inference_room, ROOM)
    assert len(after) == 1, "the contested mark's dedup_key must have blocked the re-insert"


# ---------------------------------------------------------------------------
# room context (Step 4: the participant reads the room before it marks it)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_room_context_reaches_generate_candidates_when_present(
    inference_room, monkeypatch,
):
    now = datetime.now(timezone.utc)
    await inference_room.execute(
        """INSERT INTO memories
               (id, room_id, created_at, updated_at, scope, key, content, status)
           VALUES ($1,$2,$3,$3,'room','test-memory',
                   'the strait closure would spike Brent past $100','active')""",
        uuid4(), ROOM, now,
    )
    await inference_room.execute(
        """INSERT INTO reading_items
               (id, room_id, url, title, content, summary, source, created_at)
           VALUES ($1,$2,'https://example.com/a','An article',
                   'body text here', 'a short summary', 'human', $3)""",
        uuid4(), ROOM, now,
    )
    await inference_room.execute(
        "UPDATE rooms SET trading_config = $1 WHERE id = $2",
        {"cascadePhase": "watching"}, ROOM,
    )

    # Keyed by thread — FOREIGN_ROOM is a second legitimately-active room in
    # this fixture (no memory/reading/trading_config of its own) and would
    # otherwise clobber ROOM's captured kwargs depending on iteration order.
    captured_by_thread = {}

    async def _fake(messages, active_marks, digest_rows, **kwargs):
        thread_id = messages[0]["thread_id"] if messages else None
        captured_by_thread[thread_id] = kwargs
        return [_candidate()]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    captured = captured_by_thread[TH]
    assert captured["memories"], "the seeded memory row must reach the candidate call"
    assert captured["readings"], "the seeded reading row must reach the candidate call"
    assert captured["thesis"], "the seeded trading_config must reach the candidate call"


@pytest.mark.asyncio
async def test_room_context_is_empty_tuples_when_nothing_recorded(
    inference_room, monkeypatch,
):
    captured_by_thread = {}

    async def _fake(messages, active_marks, digest_rows, **kwargs):
        thread_id = messages[0]["thread_id"] if messages else None
        captured_by_thread[thread_id] = kwargs
        return [_candidate()]

    monkeypatch.setattr(field_inference, "_generate_candidates", _fake)
    await field_inference.run(SchedulerContext(pool=_FakePool(inference_room)))

    captured = captured_by_thread[TH]
    assert captured["memories"] == ()
    assert captured["readings"] == ()
    assert captured["thesis"] == ""
