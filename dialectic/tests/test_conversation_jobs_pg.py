"""Real scheduler selection SQL must leave ordinary reading rooms alone."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from llm import night_shift, question_round
from scheduler import SchedulerContext


@pytest.mark.asyncio
async def test_scheduled_posts_require_their_room_purpose_and_human_activity(monkeypatch):
    dsn = os.getenv("DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test")
    conn = await asyncpg.connect(dsn, timeout=5)
    assert await conn.fetchval("SELECT current_database()") == "dialectic_test"
    transaction = conn.transaction()
    await transaction.start()
    try:
        # Session-local relations exercise the production queries without touching
        # persisted rooms, even if another qualification is using the test database.
        await conn.execute("""
            CREATE TEMP TABLE rooms (
                id uuid PRIMARY KEY, name text, trading_config jsonb,
                is_home boolean, linked_book_id text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE threads (id uuid PRIMARY KEY, room_id uuid) ON COMMIT DROP;
            CREATE TEMP TABLE messages (
                id uuid PRIMARY KEY, thread_id uuid, created_at timestamptz, speaker_type text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE room_memberships (room_id uuid, user_id uuid) ON COMMIT DROP;
        """)
        rooms = {}
        for name, home, book, speaker, age in [
            ("reading", False, None, "human", 0),
            ("home", True, None, "human", 0),
            ("thesis", False, "book", "human", 0),
            ("bot_only", False, "book", "llm_annotator", 0),
            ("abandoned", False, "book", "human", 15),
        ]:
            room_id, thread_id = uuid4(), uuid4()
            rooms[name] = room_id
            await conn.execute(
                "INSERT INTO rooms VALUES ($1, $2, NULL, $3, $4)", room_id, name, home, book,
            )
            await conn.execute("INSERT INTO threads VALUES ($1, $2)", thread_id, room_id)
            await conn.execute(
                "INSERT INTO messages VALUES ($1, $2, $3, $4)", uuid4(), thread_id,
                datetime.now(timezone.utc) - timedelta(days=age), speaker,
            )
            await conn.executemany("INSERT INTO room_memberships VALUES ($1, $2)",
                                   [(room_id, uuid4()), (room_id, uuid4())])

        class BorrowedPool:
            @asynccontextmanager
            async def acquire(self):
                yield conn

        pool = BorrowedPool()
        brief_rooms = await night_shift._active_rooms(pool)
        assert {r["id"] for r in brief_rooms} == {rooms["home"], rooms["thesis"]}

        monkeypatch.setattr(question_round, "is_round_day", lambda _: True)
        monkeypatch.setattr(question_round, "rooms_per_day", lambda: 0)
        already_ran = AsyncMock(return_value=True)
        monkeypatch.setattr(question_round, "_already_ran_today", already_ran)
        outcome = await question_round.question_round(SchedulerContext(pool=pool))
        assert outcome == {str(rooms["thesis"]): "already_ran"}
        assert [call.args[1] for call in already_ran.call_args_list] == [rooms["thesis"]]
    finally:
        await transaction.rollback()
        await conn.close()
