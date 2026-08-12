"""Contracts for user-specific cross-room memory promotion."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from memory.cross_session import CrossSessionMemoryManager
from models import EventType


MEMORY_ID = UUID("00000000-0000-0000-0000-000000000101")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000102")
USER_A = UUID("00000000-0000-0000-0000-000000000103")


@pytest.fixture
def memory_row() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": MEMORY_ID,
        "room_id": ROOM_ID,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "scope": "room",
        "owner_user_id": None,
        "key": "shared_concept",
        "content": "A concept shared by the room",
        "source_message_id": None,
        "created_by_user_id": USER_A,
        "status": "active",
        "invalidated_by_user_id": None,
        "invalidated_at": None,
        "invalidation_reason": None,
        "embedding": None,
        "speaker_user_id": None,
        "superseded_at": None,
        "superseded_by_memory_id": None,
    }


def test_personal_promotion_schema_and_event_contract() -> None:
    """Fresh and upgraded databases expose the same personal grant shape."""
    root = Path(__file__).resolve().parents[1]
    schema = (root / "schema.sql").read_text()
    migration = (root / "migrations" / "012_user_memory_promotions.sql").read_text()

    for sql in (schema, migration):
        assert "CREATE TABLE IF NOT EXISTS user_memory_promotions" in sql
        assert "PRIMARY KEY (memory_id, user_id)" in sql
        assert "idx_user_memory_promotions_user" in sql

    assert EventType.MEMORY_DEMOTED.value == "memory_demoted"


@pytest.mark.asyncio
async def test_promote_uses_a_personal_membership_fenced_grant(
    memory_row: dict[str, object],
) -> None:
    db = SimpleNamespace(
        fetchrow=AsyncMock(return_value=memory_row),
        execute=AsyncMock(return_value=None),
    )
    manager = CrossSessionMemoryManager(db)

    memory = await manager.promote_memory_to_global(MEMORY_ID, USER_A)

    sql = db.fetchrow.await_args.args[0]
    assert memory.id == MEMORY_ID
    assert "INSERT INTO user_memory_promotions" in sql
    assert "JOIN room_memberships" in sql
    assert "m.status = 'active'" in sql
    assert "UPDATE memories" not in sql


@pytest.mark.asyncio
async def test_demote_deletes_only_the_callers_personal_grant(
    memory_row: dict[str, object],
) -> None:
    db = SimpleNamespace(fetchrow=AsyncMock(return_value=memory_row))
    manager = CrossSessionMemoryManager(db)

    memory = await manager.demote_memory_from_global(MEMORY_ID, USER_A)

    sql = db.fetchrow.await_args.args[0]
    assert memory.id == MEMORY_ID
    assert "DELETE FROM user_memory_promotions" in sql
    assert "JOIN room_memberships" in sql
    assert "ump.user_id = $2" in sql
    assert "UPDATE memories" not in sql


@pytest.mark.asyncio
async def test_global_recall_joins_the_requesting_users_grant() -> None:
    db = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    manager = CrossSessionMemoryManager(db)
    manager._embedder = SimpleNamespace(
        embed=AsyncMock(return_value=SimpleNamespace(vector=[0.1, 0.2]))
    )

    await manager.search_user_memories(
        USER_A,
        "shared concept",
        require_global_scope=True,
    )

    sql = db.fetch.await_args.args[0]
    assert "user_memory_promotions" in sql
    assert "ump.user_id = $1" in sql
    assert "m.scope = 'global'" not in sql


@pytest.mark.asyncio
async def test_promoted_ids_are_limited_to_active_memories_in_the_users_room() -> None:
    db = SimpleNamespace(fetch=AsyncMock(return_value=[{"memory_id": MEMORY_ID}]))
    manager = CrossSessionMemoryManager(db)

    result = await manager.get_user_promoted_memory_ids(ROOM_ID, USER_A)

    assert result == [MEMORY_ID]
    sql = db.fetch.await_args.args[0]
    assert "JOIN room_memberships" in sql
    assert "m.status = 'active'" in sql
    assert db.fetch.await_args.args[1:] == (ROOM_ID, USER_A)
