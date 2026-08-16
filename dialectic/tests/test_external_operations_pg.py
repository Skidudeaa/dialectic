"""Real-PostgreSQL contracts for durable cross-service operations."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from api.external_operations import (
    ExternalOperation,
    OperationBusy,
    claim_operation,
    fail_operation,
    succeed_operation,
)


TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL",
    "postgresql://root@localhost/dialectic_test",
)
AMO = UUID("00000000-0000-4000-8000-000000000701")
DAN = UUID("00000000-0000-4000-8000-000000000702")
ROOM = UUID("00000000-0000-4000-8000-000000000703")
THREAD = UUID("00000000-0000-4000-8000-000000000704")
MESSAGE = UUID("00000000-0000-4000-8000-000000000705")
STARTED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


async def init_connection(conn: asyncpg.Connection) -> None:
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    try:
        db_pool = await asyncpg.create_pool(
            TEST_DATABASE_URL,
            min_size=1,
            max_size=4,
            init=init_connection,
        )
    except Exception as exc:
        pytest.skip(f"test database unavailable: {exc}")
        return

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM external_operations WHERE room_id = $1", ROOM)
        await conn.execute("DELETE FROM messages WHERE id = $1", MESSAGE)
        await conn.execute("DELETE FROM threads WHERE id = $1", THREAD)
        await conn.execute("DELETE FROM room_memberships WHERE room_id = $1", ROOM)
        await conn.execute("DELETE FROM rooms WHERE id = $1", ROOM)
        await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", [AMO, DAN])
        await conn.executemany(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, now(), $2)",
            [(AMO, "Amo"), (DAN, "Dan")],
        )
        await conn.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, now(), $2, $3)",
            ROOM,
            "operation-ledger-room",
            "Operation ledger",
        )
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, now(), 'Main')",
            THREAD,
            ROOM,
        )
        await conn.execute(
            """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, metadata)
               VALUES ($1, $2, 1, now(), 'llm_primary', NULL, 'text', 'proposal', $3)""",
            MESSAGE,
            THREAD,
            {"proposal": {"statement": "Brent over 90", "accepted": False}},
        )

    yield db_pool

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM external_operations WHERE room_id = $1", ROOM)
        await conn.execute("DELETE FROM messages WHERE id = $1", MESSAGE)
        await conn.execute("DELETE FROM threads WHERE id = $1", THREAD)
        await conn.execute("DELETE FROM rooms WHERE id = $1", ROOM)
        await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", [AMO, DAN])
    await db_pool.close()


async def claim(
    pool: asyncpg.Pool,
    *,
    initiated_by: UUID = AMO,
    now: datetime = STARTED_AT,
) -> ExternalOperation:
    return await claim_operation(
        pool,
        room_id=ROOM,
        kind="prediction",
        operation_key="message:proposal",
        initiated_by=initiated_by,
        source_message_id=MESSAGE,
        proposal_slot="proposal",
        now=now,
    )


@pytest.mark.asyncio
async def test_concurrent_claim_has_one_owner(pool: asyncpg.Pool) -> None:
    first, second = await asyncio.gather(
        claim(pool, initiated_by=AMO),
        claim(pool, initiated_by=DAN),
        return_exceptions=True,
    )
    assert sum(
        isinstance(value, ExternalOperation) for value in (first, second)
    ) == 1
    assert sum(isinstance(value, OperationBusy) for value in (first, second)) == 1


@pytest.mark.asyncio
async def test_expired_claim_reuses_original_actor_and_key(
    pool: asyncpg.Pool,
) -> None:
    original = await claim(pool)
    reclaimed = await claim(
        pool,
        initiated_by=DAN,
        now=STARTED_AT + timedelta(seconds=121),
    )
    assert reclaimed.id == original.id
    assert reclaimed.initiated_by == AMO
    assert reclaimed.operation_key == "message:proposal"
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_success_and_acceptance_stamp_share_the_callers_transaction(
    pool: asyncpg.Pool,
) -> None:
    operation = await claim(pool)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await succeed_operation(
                conn,
                operation,
                result={"id": "prediction-1"},
            )
        row = await conn.fetchrow(
            "SELECT status, external_result FROM external_operations WHERE id = $1",
            operation.id,
        )
        proposal = await conn.fetchval(
            "SELECT metadata->'proposal' FROM messages WHERE id = $1",
            MESSAGE,
        )

    assert row["status"] == "succeeded"
    assert row["external_result"] == {"id": "prediction-1"}
    assert proposal["statement"] == "Brent over 90"
    assert proposal["accepted"] is True
    assert proposal["accepted_by"] == str(AMO)
    assert proposal["accepted_at"]


@pytest.mark.asyncio
async def test_succeeded_claim_replays_the_stored_result(pool: asyncpg.Pool) -> None:
    operation = await claim(pool)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await succeed_operation(conn, operation, result={"id": "prediction-1"})

    replay = await claim(pool, initiated_by=DAN, now=STARTED_AT + timedelta(seconds=1))
    assert replay.status == "succeeded"
    assert replay.external_result == {"id": "prediction-1"}
    assert replay.initiated_by == AMO


@pytest.mark.asyncio
async def test_failure_is_bounded_and_reclaimable(pool: asyncpg.Pool) -> None:
    operation = await claim(pool)
    await fail_operation(pool, operation, error="x" * 800)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, last_error FROM external_operations WHERE id = $1",
            operation.id,
        )
    assert row["status"] == "failed"
    assert len(row["last_error"]) == 500

    reclaimed = await claim(pool, initiated_by=DAN, now=STARTED_AT + timedelta(seconds=1))
    assert reclaimed.status == "pending"
    assert reclaimed.attempt_count == 2
    assert reclaimed.initiated_by == AMO


@pytest.mark.asyncio
async def test_expired_owner_cannot_complete_a_reclaimed_attempt(
    pool: asyncpg.Pool,
) -> None:
    expired_owner = await claim(pool)
    current_owner = await claim(
        pool,
        initiated_by=DAN,
        now=STARTED_AT + timedelta(seconds=121),
    )

    async with pool.acquire() as conn:
        with pytest.raises(OperationBusy):
            async with conn.transaction():
                await succeed_operation(
                    conn,
                    expired_owner,
                    result={"id": "stale-result"},
                )
        row = await conn.fetchrow(
            "SELECT status, attempt_count FROM external_operations WHERE id = $1",
            current_owner.id,
        )
        accepted = await conn.fetchval(
            "SELECT metadata->'proposal'->>'accepted' FROM messages WHERE id = $1",
            MESSAGE,
        )

    assert dict(row) == {"status": "pending", "attempt_count": 2}
    assert accepted == "false"
