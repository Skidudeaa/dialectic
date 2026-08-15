"""
Real-Postgres contract for the curator's unchanged-thesis gate.

WHY real Postgres: is_unchanged() asks a JSONB question — `metadata->>
'snapshot_fingerprint'` on the room's most recent curator message — and the
answer depends on what the operator, the ORDER BY and the JSONB codec
actually do. The mocked tests in test_trading_curator.py hand fetchrow a
dict, so they assert the shape of a query that never ran; only this file
proves the statement binds its parameters and reads back what the insert
wrote.

The defect it fences (2026-08-15): Japan Rate Shock took 21 curator alerts in
three days off one unchanged snapshot. Every gate the curator had was a clock
— a 5/30-minute dedup window and an 8/day ceiling — and a snapshot repushed
every 30 minutes clears a clock simply by waiting.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from llm.trading_curator import TradingCuratorEngine, snapshot_fingerprint
from models import SpeakerType, MessageType

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM = _uid(0xC01)
THREAD = _uid(0xC02)
BASE = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

SNAPSHOT = {
    "v": 3,
    "timestamp": "2026-08-15T12:00:00Z",
    "nodeStates": {"boj_hike": "approaching", "jgb_breakout": "gated"},
    "cascadePhase": {"number": 1, "key": "shock", "status": "APPROACHING"},
    "countdowns": [{"nodeId": "boj_hike", "daysRemaining": 9}],
    "alertEvents": [],
    "marketSnapshot": {"usdJpy": 152.4},
}


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    # The SAME codec the production pool installs (api/main.py lifespan) —
    # without it a bare connection hands JSONB back as text.
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    """One room, one thread, rolled back after the test."""
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        ROOM, BASE, uuid4().hex, "Japan Rate Shock (test)",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        THREAD, ROOM, BASE, "Main",
    )
    yield db
    await tx.rollback()


async def _curator_message(db, *, at, metadata):
    await db.execute(
        """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type,
                message_type, content, metadata)
           VALUES ($1,$2,(SELECT COALESCE(MAX(sequence),0)+1 FROM messages
                          WHERE thread_id=$2),$3,$4,$5,$6,$7)""",
        uuid4(), THREAD, at, SpeakerType.LLM_ANNOTATOR.value,
        MessageType.TEXT.value, "ALERT: ...", metadata,
    )


def _engine(db):
    return TradingCuratorEngine(db, None, None)


@pytest.mark.asyncio
async def test_same_state_reads_back_as_unchanged(room):
    """The insert's fingerprint is what the gate reads — through real JSONB."""
    fp = snapshot_fingerprint(SNAPSHOT)
    await _curator_message(room, at=BASE, metadata={
        "source": "trading_curator", "snapshot_fingerprint": fp,
    })
    assert await _engine(room).is_unchanged(THREAD, fp) is True


@pytest.mark.asyncio
async def test_a_node_transition_is_news_again(room):
    await _curator_message(room, at=BASE, metadata={
        "source": "trading_curator",
        "snapshot_fingerprint": snapshot_fingerprint(SNAPSHOT),
    })
    moved = dict(SNAPSHOT, nodeStates={
        "boj_hike": "fired", "jgb_breakout": "gated",
    })
    assert await _engine(room).is_unchanged(THREAD, snapshot_fingerprint(moved)) is False


@pytest.mark.asyncio
async def test_only_the_latest_alert_is_consulted(room):
    """A state that RETURNS to one described two alerts ago is news.

    WHY: the question is "is this new since we last spoke", not "have we
    ever said this" — a thesis that fires, reverts, and fires again is three
    events, and a room told only about the first would be misled.
    """
    old = snapshot_fingerprint(SNAPSHOT)
    moved = snapshot_fingerprint(dict(SNAPSHOT, nodeStates={"boj_hike": "fired"}))
    await _curator_message(room, at=BASE, metadata={
        "source": "trading_curator", "snapshot_fingerprint": old,
    })
    await _curator_message(room, at=BASE + timedelta(minutes=30), metadata={
        "source": "trading_curator", "snapshot_fingerprint": moved,
    })
    assert await _engine(room).is_unchanged(THREAD, old) is False
    assert await _engine(room).is_unchanged(THREAD, moved) is True


@pytest.mark.asyncio
async def test_pre_fingerprint_alerts_do_not_silence_the_room(room):
    """Every curator message already in production lacks the key.

    `metadata->>'snapshot_fingerprint'` is SQL NULL there, and NULL must read
    as "this is news" — the opposite failure would be a permanently muted
    trading room, which is worse than the noise this gate exists to stop.
    """
    await _curator_message(room, at=BASE, metadata={
        "source": "trading_curator",
        "snapshot_timestamp": "2026-08-15T12:00:00Z",
        "snapshot_v": 2,
    })
    assert await _engine(room).is_unchanged(THREAD, snapshot_fingerprint(SNAPSHOT)) is False


@pytest.mark.asyncio
async def test_another_rooms_alert_cannot_silence_this_thread(room):
    """The gate is thread-scoped; a sibling room's identical state is its own."""
    other_room, other_thread = _uid(0xC11), _uid(0xC12)
    await room.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        other_room, BASE, uuid4().hex, "Iran/Hormuz (test)",
    )
    await room.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        other_thread, other_room, BASE, "Main",
    )
    fp = snapshot_fingerprint(SNAPSHOT)
    await room.execute(
        """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type,
                message_type, content, metadata)
           VALUES ($1,$2,1,$3,$4,$5,$6,$7)""",
        uuid4(), other_thread, BASE, SpeakerType.LLM_ANNOTATOR.value,
        MessageType.TEXT.value, "ALERT: ...",
        {"source": "trading_curator", "snapshot_fingerprint": fp},
    )
    assert await _engine(room).is_unchanged(THREAD, fp) is False


@pytest.mark.asyncio
async def test_a_non_curator_annotation_is_not_a_curator_alert(room):
    """reading_echo and the morning brief post as llm_annotator too."""
    fp = snapshot_fingerprint(SNAPSHOT)
    await _curator_message(room, at=BASE, metadata={
        "source": "reading_echo", "snapshot_fingerprint": fp,
    })
    assert await _engine(room).is_unchanged(THREAD, fp) is False
