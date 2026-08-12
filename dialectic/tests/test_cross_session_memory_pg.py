"""Real-Postgres acceptance tests for personal cross-room memory grants."""

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from memory.cross_session import CrossSessionMemoryManager
from memory.embeddings import MockEmbeddings
from memory.manager import MemoryManager


TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL",
    "postgresql://root@localhost/dialectic_test",
)


def _json_encoder(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, UUID):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"Not JSON serializable: {type(item)}")

    return json.dumps(value, default=default)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as error:
        pytest.skip(f"test database unavailable: {error}")
        return

    await connection.set_type_codec(
        "jsonb",
        encoder=_json_encoder,
        decoder=json.loads,
        schema="pg_catalog",
    )
    transaction = connection.transaction()
    await transaction.start()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@dataclass(frozen=True)
class CrossSessionRooms:
    source_room: UUID
    user_a_second_room: UUID
    user_a: UUID
    user_b: UUID
    outsider: UUID
    memory_manager: MemoryManager
    cross_session_manager: CrossSessionMemoryManager


@pytest_asyncio.fixture
async def rooms(db: asyncpg.Connection) -> CrossSessionRooms:
    source_room = uuid4()
    user_a_second_room = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    outsider = uuid4()
    now = datetime.now(timezone.utc)

    for room_id, name in (
        (source_room, "Personal Promotion Source"),
        (user_a_second_room, "Personal Promotion Target"),
    ):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, $4)",
            room_id,
            now,
            f"test-{room_id}",
            name,
        )

    for user_id, name in (
        (user_a, "Promoter"),
        (user_b, "Collaborator"),
        (outsider, "Outsider"),
    ):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, $3)",
            user_id,
            now,
            name,
        )

    for room_id, user_id in (
        (source_room, user_a),
        (source_room, user_b),
        (user_a_second_room, user_a),
    ):
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            room_id,
            user_id,
            now,
        )

    memory_manager = MemoryManager(db)
    memory_manager._embedder = MockEmbeddings()
    cross_session_manager = CrossSessionMemoryManager(db)
    cross_session_manager._embedder = MockEmbeddings()
    return CrossSessionRooms(
        source_room=source_room,
        user_a_second_room=user_a_second_room,
        user_a=user_a,
        user_b=user_b,
        outsider=outsider,
        memory_manager=memory_manager,
        cross_session_manager=cross_session_manager,
    )


@pytest.mark.asyncio
async def test_personal_promotion_is_visible_only_to_the_promoter(
    db: asyncpg.Connection,
    rooms: CrossSessionRooms,
) -> None:
    content = "personal promotion acceptance concept"
    memory = await rooms.memory_manager.add_memory(
        rooms.source_room,
        "shared_concept",
        content,
        created_by_user_id=rooms.user_a,
    )

    await rooms.cross_session_manager.promote_memory_to_global(memory.id, rooms.user_a)

    user_a_hits = await rooms.cross_session_manager.get_relevant_cross_room_memories(
        rooms.user_a,
        rooms.user_a_second_room,
        content,
    )
    user_b_hits = await rooms.cross_session_manager.get_relevant_cross_room_memories(
        rooms.user_b,
        uuid4(),
        content,
    )

    assert memory.id in {hit.memory.id for hit in user_a_hits}
    assert memory.id not in {hit.memory.id for hit in user_b_hits}
    assert await db.fetchval(
        "SELECT scope FROM memories WHERE id = $1",
        memory.id,
    ) == "room"


@pytest.mark.asyncio
async def test_promotion_fails_closed_for_outsiders_and_inactive_memories(
    rooms: CrossSessionRooms,
) -> None:
    memory = await rooms.memory_manager.add_memory(
        rooms.source_room,
        "private_source",
        "membership fenced promotion",
        created_by_user_id=rooms.user_a,
    )

    with pytest.raises(ValueError, match="not found or inaccessible"):
        await rooms.cross_session_manager.promote_memory_to_global(
            memory.id,
            rooms.outsider,
        )

    await rooms.memory_manager.invalidate_memory(memory.id, rooms.user_a)
    with pytest.raises(ValueError, match="not found or inaccessible"):
        await rooms.cross_session_manager.promote_memory_to_global(
            memory.id,
            rooms.user_a,
        )


@pytest.mark.asyncio
async def test_promote_and_demote_are_idempotent_and_emit_one_event_each(
    db: asyncpg.Connection,
    rooms: CrossSessionRooms,
) -> None:
    memory = await rooms.memory_manager.add_memory(
        rooms.source_room,
        "idempotent_promotion",
        "one grant and one removal event",
        created_by_user_id=rooms.user_a,
    )

    await rooms.cross_session_manager.promote_memory_to_global(memory.id, rooms.user_a)
    await rooms.cross_session_manager.promote_memory_to_global(memory.id, rooms.user_a)
    await rooms.cross_session_manager.demote_memory_from_global(memory.id, rooms.user_a)
    await rooms.cross_session_manager.demote_memory_from_global(memory.id, rooms.user_a)

    assert await db.fetchval(
        """
        SELECT count(*)
        FROM user_memory_promotions
        WHERE memory_id = $1 AND user_id = $2
        """,
        memory.id,
        rooms.user_a,
    ) == 0
    event_counts = await db.fetch(
        """
        SELECT event_type, count(*) AS count
        FROM events
        WHERE payload->>'memory_id' = $1
          AND event_type IN ('memory_promoted', 'memory_demoted')
        GROUP BY event_type
        """,
        str(memory.id),
    )
    assert {row["event_type"]: row["count"] for row in event_counts} == {
        "memory_promoted": 1,
        "memory_demoted": 1,
    }
