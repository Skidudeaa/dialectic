"""Real-Postgres contract for GET /rooms/{id}/activity/daily's SQL — the
working surface's volume chart. The day bucket is the room's own day
(America/Chicago) and the window is `days` calendar days ending today.

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

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, THREAD, AMO = _uid(0xA11), _uid(0xA12), _uid(0xA13)

# The route's query, verbatim — see api/workspace.py::get_daily_activity.
DAILY_SQL = """SELECT (m.created_at AT TIME ZONE 'America/Chicago')::date AS day,
                  m.speaker_type, count(*)::int AS n
           FROM messages m
           JOIN threads t ON t.id = m.thread_id
           WHERE t.room_id = $1
             AND m.is_deleted = FALSE
             AND m.created_at >= now() - ($2::int * interval '1 day')
           GROUP BY 1, 2"""


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
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    tx = db.transaction()
    await tx.start()
    now = datetime.now(timezone.utc)
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        ROOM, now, uuid4().hex, "Activity Room",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        THREAD, ROOM, now, "Main",
    )
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
        AMO, now, "Amo",
    )
    seeds = [
        ("human", AMO, now - timedelta(hours=1), False),
        ("human", AMO, now - timedelta(hours=2), False),
        ("llm_primary", None, now - timedelta(hours=1), False),
        ("llm_annotator", None, now - timedelta(hours=1), True),   # deleted: excluded
        ("human", AMO, now - timedelta(days=40), False),           # outside the window
    ]
    for i, (speaker, user, at, deleted) in enumerate(seeds):
        await db.execute(
            """INSERT INTO messages
                   (id, thread_id, sequence, created_at, speaker_type, user_id,
                    message_type, content, is_deleted)
               VALUES ($1,$2,$3,$4,$5,$6,'text','x',$7)""",
            uuid4(), THREAD, i + 1, at, speaker, user, deleted,
        )
    yield db
    await tx.rollback()


@pytest.mark.asyncio
async def test_daily_counts_bucket_by_room_day_and_exclude_deleted(room):
    rows = await room.fetch(DAILY_SQL, ROOM, 14)
    by = {(str(r["day"]), r["speaker_type"]): r["n"] for r in rows}
    assert sum(n for (_, s), n in by.items() if s == "human") == 2
    assert sum(n for (_, s), n in by.items() if s == "llm_primary") == 1
    assert not any(s == "llm_annotator" for (_, s) in by)
    # Every bucket is a real date and within the window.
    for (day, _), _n in by.items():
        assert datetime.fromisoformat(day).date() >= (datetime.now(timezone.utc) - timedelta(days=14)).date()
