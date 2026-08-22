"""
Real-Postgres contract for GET /rooms/{room_id}/threads/{thread_id}/decisions
(api/decisions.py).

WHY real Postgres and not the mocked HTTP contract in test_decisions_api.py:
that file proves the room-token/membership FENCE (the auth layer) with a
fake `db.fetch` that asserts its own arguments. It cannot prove the SQL
itself actually excludes a foreign room's or foreign thread's rows — a
mocked fetch returns whatever the test hands it regardless of the WHERE
clause. Only a real query, against rows that really live in a DIFFERENT
room/thread, can show that.

This calls the route FUNCTION directly against a live connection (same
idiom as tests/test_self_model_reducer_pg.py) rather than routing through
TestClient — the auth layer is already covered above; what matters here is
the query and the row shaping, exercised through the REAL write path
(SelfModel.log_decision) so a fixture never invents a shape production
would not.

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

from api.auth.dependencies import AuthenticatedUser
from api.decisions import get_thread_decisions
from llm.heuristics import InterjectionDecision
from llm.self_model import SelfModel

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


USER = _uid(0xDEC1DE)
ROOM = _uid(0xDEC1D0)
THREAD = _uid(0xDEC1D1)
OTHER_ROOM = _uid(0xDEC1D2)
OTHER_THREAD = _uid(0xDEC1D3)
BASE = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
TOKEN = "decisions-test-token"


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
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, now(), 'Tester')",
            USER,
        )
        await conn.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            ROOM, BASE, TOKEN, "Decisions room (test)",
        )
        await conn.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,now())",
            ROOM, USER,
        )
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
            THREAD, ROOM, BASE, "Main",
        )
        # A second room the caller is NOT a member of, with its own thread —
        # what the leak test below proves stays invisible.
        await conn.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            OTHER_ROOM, BASE, uuid4().hex, "Someone else's room",
        )
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
            OTHER_THREAD, OTHER_ROOM, BASE, "Main",
        )
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


async def _message(db, thread_id: UUID) -> UUID:
    mid = uuid4()
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
                                 speaker_type, message_type, content)
           VALUES ($1,$2,1,$3,'llm_primary','text','...')""",
        mid, thread_id, BASE,
    )
    return mid


def _decision(reason: str, **kw) -> InterjectionDecision:
    return InterjectionDecision(
        should_interject=True, reason=reason, confidence=kw.pop("confidence", 0.9),
        use_provoker=kw.pop("use_provoker", False),
        considered_reasons=[],
    )


def _caller() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=USER, email="t@test", email_verified=True, display_name="Tester",
    )


@pytest.mark.asyncio
async def test_returns_the_decision_keyed_by_its_message(db):
    mid = await _message(db, THREAD)
    await SelfModel(db).log_decision(
        room_id=ROOM, thread_id=THREAD, triggered_by_message_id=None,
        decision=_decision("explicit_mention", confidence=1.0),
        response_message_id=mid, mode="primary",
    )
    result = await get_thread_decisions(
        room_id=ROOM, thread_id=THREAD, token=TOKEN,
        current_user=_caller(), db=db,
    )
    assert list(result.decisions.keys()) == [str(mid)]
    entry = result.decisions[str(mid)]
    assert entry.reason == "explicit_mention"
    assert entry.mode == "primary"
    assert entry.confidence == 1.0
    assert entry.use_provoker is False


@pytest.mark.asyncio
async def test_silence_decisions_never_appear_they_produced_no_message(db):
    """should_interject=False decisions have NULL response_message_id — the
    route's own WHERE excludes them, and there is no message id to key
    them by even if it did not."""
    await SelfModel(db).log_decision(
        room_id=ROOM, thread_id=THREAD, triggered_by_message_id=None,
        decision=InterjectionDecision(
            should_interject=False, reason="no_trigger", confidence=0.0,
            use_provoker=False, considered_reasons=[],
        ),
        mode="silence",
    )
    result = await get_thread_decisions(
        room_id=ROOM, thread_id=THREAD, token=TOKEN,
        current_user=_caller(), db=db,
    )
    assert result.decisions == {}


@pytest.mark.asyncio
async def test_a_decision_logged_in_a_different_room_does_not_leak(db):
    """The security-relevant assertion. A decision that happens to share
    NOTHING with this room except existing in the same database must not
    appear just because some other query bug widened the WHERE clause."""
    foreign_mid = await _message(db, OTHER_THREAD)
    await SelfModel(db).log_decision(
        room_id=OTHER_ROOM, thread_id=OTHER_THREAD, triggered_by_message_id=None,
        decision=_decision("explicit_mention", confidence=1.0),
        response_message_id=foreign_mid, mode="primary",
    )
    # Also log one that legitimately belongs to THIS thread, so an empty
    # result would not silently pass this test for the wrong reason.
    own_mid = await _message(db, THREAD)
    await SelfModel(db).log_decision(
        room_id=ROOM, thread_id=THREAD, triggered_by_message_id=None,
        decision=_decision("question_detected", confidence=0.7),
        response_message_id=own_mid, mode="primary",
    )

    result = await get_thread_decisions(
        room_id=ROOM, thread_id=THREAD, token=TOKEN,
        current_user=_caller(), db=db,
    )
    assert str(foreign_mid) not in result.decisions
    assert list(result.decisions.keys()) == [str(own_mid)]


@pytest.mark.asyncio
async def test_your_own_room_token_cannot_pull_a_foreign_thread(db):
    """The actual attack `room_id = $1` defends against — NOT two unrelated
    rooms leaking into each other (thread_id alone already prevents that,
    since a thread belongs to exactly one room), but a caller who holds a
    LEGITIMATE token and membership for THEIR OWN room supplying a thread_id
    that belongs to someone else's room instead. Without the room_id
    predicate in the SQL, `thread_id = $2` alone would happily return that
    foreign thread's decisions, because thread_id alone already uniquely
    resolves them — the room_id check is what proves the caller was ever
    authorized to see THIS thread at all.
    """
    foreign_mid = await _message(db, OTHER_THREAD)
    await SelfModel(db).log_decision(
        room_id=OTHER_ROOM, thread_id=OTHER_THREAD, triggered_by_message_id=None,
        decision=_decision("explicit_mention", confidence=1.0),
        response_message_id=foreign_mid, mode="primary",
    )

    # The caller's OWN room_id and token — genuinely authorized for ROOM —
    # paired with a thread_id from a room they are not a member of.
    result = await get_thread_decisions(
        room_id=ROOM, thread_id=OTHER_THREAD, token=TOKEN,
        current_user=_caller(), db=db,
    )
    assert result.decisions == {}, (
        "a caller authorized only for ROOM pulled decisions from OTHER_ROOM's "
        "thread by supplying its thread_id — the room_id fence did not hold"
    )


@pytest.mark.asyncio
async def test_null_inputs_survive_as_none_not_invented_zeros(db):
    """A forced turn (wire/silence-follow-up/protocol) never runs the
    heuristic rungs, so turn_count/novelty/unsurfaced_count are genuinely
    absent, not zero."""
    mid = await _message(db, THREAD)
    await SelfModel(db).log_decision(
        room_id=ROOM, thread_id=THREAD, triggered_by_message_id=None,
        decision=_decision("wire_interjection", confidence=1.0),
        response_message_id=mid, mode="primary",
        # human_turn_count / semantic_novelty / unsurfaced_memory_count
        # deliberately omitted — force_response never computes them.
    )
    result = await get_thread_decisions(
        room_id=ROOM, thread_id=THREAD, token=TOKEN,
        current_user=_caller(), db=db,
    )
    entry = result.decisions[str(mid)]
    assert entry.human_turn_count is None
    assert entry.semantic_novelty is None
    assert entry.unsurfaced_memory_count is None
