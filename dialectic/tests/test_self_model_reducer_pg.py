"""
Real-Postgres contract for the participation reducer.

WHY real Postgres: the defect this fences was a PARSE-time failure. asyncpg
sends parameters untyped and lets Postgres deduce them, and
`COALESCE($7, $2)` is two unknowns — which Postgres resolves to TEXT, then
contradicts `last_spoke_at = $2` and raises "inconsistent types deduced for
parameter $2" before a single row is touched. No mocked test can see that:
a fake `db.execute` accepts any string, and a source-text assertion cannot
tell a working statement from a statement-shaped one. Only a real server
binds the parameters.

The defect (2026-08-09 → 2026-08-16, seven days live): the commit that added
the FSM columns added the untyped COALESCE with them. `log_decision` wraps
the whole reducer in `except Exception` — deliberately, so self-model
failures never block the conversation — so the only symptom was a WARNING
line. Blast radius, measured on the live DB:

  * `llm_participation_state` last wrote 2026-08-09 04:25 while
    `llm_decisions` took 107 new rows in the following week. The
    self-awareness block rendered into every prompt was frozen.
  * `log_decision` returned None instead of the decision id, so the
    `if decision_id:` gate in orchestrator.py skipped
    `_schedule_effectiveness_measurement` on EVERY speak. The instrument
    repaired on 2026-08-15 (the 'HUMAN' vs 'human' predicate) had never
    been reached: 14 speaks on 2026-08-16, 0 measured.

Both assertions below therefore matter. The row proves the reducer runs;
the returned id proves the caller can still schedule what depends on it.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from llm.heuristics import InterjectionDecision
from llm.self_model import SelfModel

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM = _uid(0x5E1F)
THREAD = _uid(0x5E2F)
BASE = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        ROOM, BASE, uuid4().hex, "Reducer contract (test)",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        THREAD, ROOM, BASE, "Main",
    )
    yield db
    await tx.rollback()


def _decision(*, speak: bool) -> InterjectionDecision:
    return InterjectionDecision(
        should_interject=speak,
        reason="question_detected" if speak else "no_trigger",
        confidence=0.82,
        use_provoker=False,
        considered_reasons=["question_detected"],
    )


async def _state(db):
    return await db.fetchrow(
        "SELECT * FROM llm_participation_state WHERE room_id = $1", ROOM
    )


# ── the speak branch ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_speak_writes_the_reducer_row_and_returns_the_decision_id(room):
    """The exact production call, with production parameter types.

    `state_entered_at=None` is the common case and the one that broke: it is
    the argument whose type Postgres could not deduce.
    """
    db = room
    response_id = uuid4()
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
                                 speaker_type, message_type, content)
           VALUES ($1,$2,1,$3,'llm_primary','text','...')""",
        response_id, THREAD, BASE,
    )

    decision_id = await SelfModel(db).log_decision(
        room_id=ROOM,
        thread_id=THREAD,
        triggered_by_message_id=None,
        decision=_decision(speak=True),
        semantic_novelty=0.91,
        speaker_balance={"amo": 3, "dan": 1},
        message_count=12,
        response_message_id=response_id,
        mode="primary",
        tool_calls=None,
        fsm_state=None,
        state_entered_at=None,
        state_source=None,
    )

    # The orchestrator gates _schedule_effectiveness_measurement on this id.
    # A swallowed reducer exception returns None and silently skips it.
    assert decision_id is not None, "log_decision returned None — reducer raised"

    row = await _state(db)
    assert row is not None, "no llm_participation_state row was written"
    assert row["total_messages_sent"] == 1
    assert row["primary_count"] == 1
    assert row["last_mode"] == "primary"
    assert row["last_spoke_message_id"] == response_id
    # The COALESCE defaults, which is where the untyped parameters lived.
    assert row["fsm_state"] == "engaged"
    assert row["state_source"] == "observed"
    assert row["state_entered_at"] is not None


@pytest.mark.asyncio
async def test_explicit_fsm_state_is_stored_not_defaulted(room):
    """When the caller DOES supply the FSM columns they must survive.

    Guards the other direction of the same COALESCE: pinning a type must not
    turn the supplied value into the fallback.
    """
    db = room
    entered = datetime(2026, 8, 16, 11, 30, tzinfo=timezone.utc)
    decision_id = await SelfModel(db).log_decision(
        room_id=ROOM,
        thread_id=THREAD,
        triggered_by_message_id=None,
        decision=_decision(speak=False),
        mode="silence",
        fsm_state="question_pending",
        state_entered_at=entered,
        state_source="derived",
    )
    assert decision_id is not None

    row = await _state(db)
    assert row["fsm_state"] == "question_pending"
    assert row["state_entered_at"] == entered
    assert row["state_source"] == "derived"


# ── the silence branch ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_silence_writes_the_reducer_row(room):
    """The silence INSERT carries its own copy of the same COALESCE."""
    db = room
    decision_id = await SelfModel(db).log_decision(
        room_id=ROOM,
        thread_id=THREAD,
        triggered_by_message_id=None,
        decision=_decision(speak=False),
        mode="silence",
        fsm_state=None,
        state_entered_at=None,
        state_source=None,
    )
    assert decision_id is not None

    row = await _state(db)
    assert row is not None, "no llm_participation_state row was written"
    assert row["total_silences"] == 1
    assert row["turns_since_last_spoke"] == 1
    assert row["fsm_state"] == "engaged"


@pytest.mark.asyncio
async def test_reducer_accumulates_across_decisions(room):
    """The ON CONFLICT arm — where the same COALESCE runs a second time.

    A first-insert-only fix would pass the tests above and still leave every
    subsequent turn unrecorded.
    """
    db = room
    sm = SelfModel(db)
    for _ in range(3):
        assert await sm.log_decision(
            room_id=ROOM, thread_id=THREAD, triggered_by_message_id=None,
            decision=_decision(speak=False), mode="silence",
        ) is not None

    row = await _state(db)
    assert row["total_silences"] == 3
    assert row["turns_since_last_spoke"] == 3
