"""Real-PostgreSQL unread-count semantics."""

import os
from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from api.notifications.service import (
    calculate_badge_count,
    get_all_room_unread_counts,
    get_room_unread_count,
)


TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL",
    "postgresql://root@localhost/dialectic_test",
)
VIEWER = UUID("00000000-0000-4000-8000-000000000601")
OTHER = UUID("00000000-0000-4000-8000-000000000602")
ROOM = UUID("00000000-0000-4000-8000-000000000603")
THREAD = UUID("00000000-0000-4000-8000-000000000604")


@pytest_asyncio.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as exc:
        pytest.skip(f"test database unavailable: {exc}")
        return
    transaction = conn.transaction()
    await transaction.start()
    await conn.executemany(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1, now(), $2)",
        [(VIEWER, "Viewer"), (OTHER, "Other")],
    )
    await conn.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, now(), $2, $3)",
        ROOM,
        "unread-contract-room",
        "Unread contract",
    )
    await conn.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, now())",
        ROOM,
        VIEWER,
    )
    await conn.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, now(), 'Main')",
        THREAD,
        ROOM,
    )
    yield conn
    await transaction.rollback()
    await conn.close()


async def insert_message(
    db: asyncpg.Connection,
    number: int,
    *,
    speaker_type: str,
    user_id: UUID | None,
) -> UUID:
    message_id = UUID(f"00000000-0000-4000-8000-{number:012x}")
    await db.execute(
        """INSERT INTO messages
           (id, thread_id, sequence, created_at, speaker_type, user_id, message_type, content)
           VALUES ($1, $2, $3, now(), $4, $5, 'text', $6)""",
        message_id,
        THREAD,
        number,
        speaker_type,
        user_id,
        f"message {number}",
    )
    return message_id


@pytest.mark.asyncio
async def test_null_authored_llm_message_counts_as_unread(
    db: asyncpg.Connection,
) -> None:
    await insert_message(db, 1, speaker_type="llm_primary", user_id=None)
    await insert_message(db, 2, speaker_type="human", user_id=VIEWER)
    read_message = await insert_message(db, 3, speaker_type="human", user_id=OTHER)
    await db.execute(
        """INSERT INTO message_receipts (message_id, user_id, receipt_type)
           VALUES ($1, $2, 'read')""",
        read_message,
        VIEWER,
    )

    assert await calculate_badge_count(db, str(VIEWER)) == 1
    assert await get_room_unread_count(db, str(VIEWER), str(ROOM)) == 1
    assert await get_all_room_unread_counts(db, str(VIEWER)) == {str(ROOM): 1}


@pytest.mark.asyncio
async def test_lowercase_system_message_does_not_count(
    db: asyncpg.Connection,
) -> None:
    await insert_message(db, 1, speaker_type="system", user_id=OTHER)

    assert await calculate_badge_count(db, str(VIEWER)) == 0
    assert await get_room_unread_count(db, str(VIEWER), str(ROOM)) == 0
    assert await get_all_room_unread_counts(db, str(VIEWER)) == {}
