"""Real-PostgreSQL contracts for cross-thread message pagination."""

import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

import api.main as main_mod


TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL",
    "postgresql://root@localhost/dialectic_test",
)
ROOM = UUID("00000000-0000-4000-8000-000000000801")
PARENT = UUID("00000000-0000-4000-8000-000000000802")
CHILD = UUID("00000000-0000-4000-8000-000000000803")
M1 = UUID("00000000-0000-4000-8000-000000000811")
M2 = UUID("00000000-0000-4000-8000-000000000812")
M3 = UUID("00000000-0000-4000-8000-000000000813")
M4 = UUID("00000000-0000-4000-8000-000000000814")
CREATED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


async def init_connection(connection: asyncpg.Connection) -> None:
    for typename in ("jsonb", "json"):
        await connection.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


@pytest_asyncio.fixture
async def ancestry_db() -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as exc:
        pytest.skip(f"test database unavailable: {exc}")
        return
    await init_connection(connection)
    transaction = connection.transaction()
    await transaction.start()

    await connection.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, now(), $2, $3)",
        ROOM,
        "ancestry-pagination-token",
        "Pagination room",
    )
    await connection.execute(
        """INSERT INTO threads
           (id, room_id, created_at, title, parent_thread_id, fork_point_message_id)
           VALUES ($1, $2, $3, 'Parent', NULL, NULL)""",
        PARENT,
        ROOM,
        CREATED_AT,
    )
    await connection.executemany(
        """INSERT INTO messages
           (id, thread_id, sequence, created_at, speaker_type, message_type, content)
           VALUES ($1, $2, $3, $4, 'llm_primary', 'text', $5)""",
        [
            (M1, PARENT, 1, CREATED_AT, "parent one"),
            (M2, PARENT, 2, CREATED_AT + timedelta(minutes=1), "parent two"),
        ],
    )
    await connection.execute(
        """INSERT INTO threads
           (id, room_id, created_at, title, parent_thread_id, fork_point_message_id)
           VALUES ($1, $2, $3, 'Child', $4, $5)""",
        CHILD,
        ROOM,
        CREATED_AT + timedelta(minutes=2),
        PARENT,
        M2,
    )
    await connection.executemany(
        """INSERT INTO messages
           (id, thread_id, sequence, created_at, speaker_type, message_type, content)
           VALUES ($1, $2, $3, $4, 'llm_primary', 'text', $5)""",
        [
            # M2 and M3 deliberately share a timestamp; UUID is the tie-breaker.
            (M3, CHILD, 1, CREATED_AT + timedelta(minutes=1), "child one"),
            (M4, CHILD, 2, CREATED_AT + timedelta(minutes=3), "child two"),
        ],
    )

    yield connection

    await transaction.rollback()
    await connection.close()


async def page(
    db: asyncpg.Connection,
    *,
    before_cursor: str | None = None,
    after_cursor: str | None = None,
    before_sequence: int | None = None,
    after_sequence: int | None = None,
) -> main_mod.PaginatedMessagesResponse:
    return await main_mod.get_messages(
        thread_id=CHILD,
        token="ancestry-pagination-token",
        include_ancestry=True,
        limit=2,
        before_cursor=before_cursor,
        after_cursor=after_cursor,
        before_sequence=before_sequence,
        after_sequence=after_sequence,
        db=db,
    )


def message_ids(response: main_mod.PaginatedMessagesResponse) -> list[UUID]:
    return [message.id for message in response.messages]


def test_cursor_round_trip_is_url_safe() -> None:
    cursor = main_mod.encode_message_cursor(CREATED_AT, M1)
    assert "+" not in cursor and "/" not in cursor and "=" not in cursor
    assert main_mod.decode_message_cursor(cursor) == (CREATED_AT, M1)


@pytest.mark.asyncio
async def test_ancestry_pages_are_stable_with_duplicate_thread_sequences(
    ancestry_db: asyncpg.Connection,
) -> None:
    first = await page(ancestry_db)
    second = await page(ancestry_db, before_cursor=first.oldest_cursor)

    assert message_ids(first) == [M3, M4]
    assert message_ids(second) == [M1, M2]
    assert set(message_ids(first)).isdisjoint(message_ids(second))
    assert first.has_more_before is True
    assert second.has_more_before is False
    assert second.has_more_after is True


@pytest.mark.asyncio
async def test_after_cursor_returns_the_newer_ancestry_window(
    ancestry_db: asyncpg.Connection,
) -> None:
    latest = await page(ancestry_db)
    older = await page(ancestry_db, before_cursor=latest.oldest_cursor)
    newer = await page(ancestry_db, after_cursor=older.newest_cursor)

    assert message_ids(newer) == [M3, M4]
    assert newer.has_more_before is True
    assert newer.has_more_after is False


@pytest.mark.asyncio
async def test_sequence_cursor_with_ancestry_is_rejected(
    ancestry_db: asyncpg.Connection,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await page(ancestry_db, before_sequence=3)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_malformed_opaque_cursor_is_rejected(
    ancestry_db: asyncpg.Connection,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await page(ancestry_db, before_cursor="not+a/cursor=")
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid message cursor"


@pytest.mark.asyncio
async def test_ancestry_response_does_not_claim_one_sequence_is_global(
    ancestry_db: asyncpg.Connection,
) -> None:
    response = await page(ancestry_db)
    assert response.oldest_sequence is None
    assert response.newest_sequence is None
    assert response.oldest_cursor is not None
    assert response.newest_cursor is not None


@pytest.mark.asyncio
async def test_ancestry_query_plan_records_current_indexes(
    ancestry_db: asyncpg.Connection,
) -> None:
    query = (
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        + main_mod.ANCESTRY_MESSAGES_BEFORE_QUERY
    )
    plan = await ancestry_db.fetchval(query, CHILD, None, None, 3)
    print(json.dumps(plan, indent=2))

    rows = await ancestry_db.fetch(
        main_mod.ANCESTRY_MESSAGES_BEFORE_QUERY,
        CHILD,
        None,
        None,
        3,
    )
    assert len(rows) <= 3
