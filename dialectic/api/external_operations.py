"""Durable claims for writes that cross a network boundary."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg

from proposal_envelope import ACCEPT_SLOT_SQL, acceptance_stamp


LEASE_SECONDS = 120


@dataclass(frozen=True)
class ExternalOperation:
    """One durable external write attempt and its stable source coordinate."""

    id: UUID
    room_id: UUID
    operation_kind: str
    operation_key: str
    initiated_by: UUID
    status: str
    source_message_id: UUID | None
    proposal_slot: str | None
    attempt_count: int
    lease_expires_at: datetime
    external_result: dict | None


class OperationBusy(RuntimeError):
    """The stable operation is still leased to another request."""

    def __init__(self, operation: ExternalOperation) -> None:
        super().__init__(f"External operation is already pending: {operation.operation_key}")
        self.operation = operation


def _from_row(row: asyncpg.Record) -> ExternalOperation:
    return ExternalOperation(
        id=row["id"],
        room_id=row["room_id"],
        operation_kind=row["operation_kind"],
        operation_key=row["operation_key"],
        initiated_by=row["initiated_by_user_id"],
        status=row["status"],
        source_message_id=row["source_message_id"],
        proposal_slot=row["proposal_slot"],
        attempt_count=row["attempt_count"],
        lease_expires_at=row["lease_expires_at"],
        external_result=row["external_result"],
    )


def _assert_same_operation(
    row: asyncpg.Record,
    *,
    room_id: UUID,
    kind: str,
    operation_key: str,
    source_message_id: UUID | None,
    proposal_slot: str | None,
) -> None:
    expected = (room_id, kind, operation_key, source_message_id, proposal_slot)
    actual = (
        row["room_id"],
        row["operation_kind"],
        row["operation_key"],
        row["source_message_id"],
        row["proposal_slot"],
    )
    if actual != expected:
        raise ValueError("Operation key or proposal coordinate is already in use")


async def claim_operation(
    pool: asyncpg.Pool,
    *,
    room_id: UUID,
    kind: str,
    operation_key: str,
    initiated_by: UUID,
    source_message_id: UUID | None = None,
    proposal_slot: str | None = None,
    now: datetime | None = None,
) -> ExternalOperation:
    """Claim new work, replay success, or reclaim failed/expired work."""
    if (source_message_id is None) != (proposal_slot is None):
        raise ValueError("source_message_id and proposal_slot must be provided together")
    claimed_at = now or datetime.now(timezone.utc)
    lease_expires_at = claimed_at + timedelta(seconds=LEASE_SECONDS)

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO external_operations
                   (id, room_id, operation_kind, operation_key,
                    initiated_by_user_id, source_message_id, proposal_slot,
                    status, attempt_count, lease_expires_at, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7,
                           'pending', 1, $8, $9, $9)
                   ON CONFLICT DO NOTHING
                   RETURNING *""",
                uuid4(),
                room_id,
                kind,
                operation_key,
                initiated_by,
                source_message_id,
                proposal_slot,
                lease_expires_at,
                claimed_at,
            )
            inserted = row is not None
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM external_operations WHERE operation_key = $1 FOR UPDATE",
                    operation_key,
                )
            if row is None and source_message_id is not None:
                row = await conn.fetchrow(
                    """SELECT * FROM external_operations
                       WHERE source_message_id = $1 AND proposal_slot = $2
                       FOR UPDATE""",
                    source_message_id,
                    proposal_slot,
                )
            if row is None:
                raise RuntimeError("Operation conflict did not resolve to an existing row")

            _assert_same_operation(
                row,
                room_id=room_id,
                kind=kind,
                operation_key=operation_key,
                source_message_id=source_message_id,
                proposal_slot=proposal_slot,
            )
            operation = _from_row(row)
            if inserted:
                return operation
            if operation.status == "succeeded":
                return operation
            if (
                operation.status == "pending"
                and operation.lease_expires_at > claimed_at
                and not inserted
            ):
                raise OperationBusy(operation)

            reclaimed = await conn.fetchrow(
                """UPDATE external_operations
                   SET status = 'pending',
                       attempt_count = attempt_count + 1,
                       lease_expires_at = $2,
                       external_result = NULL,
                       last_error = NULL,
                       updated_at = $3
                   WHERE id = $1
                   RETURNING *""",
                operation.id,
                lease_expires_at,
                claimed_at,
            )
            return _from_row(reclaimed)


async def succeed_operation(
    db: asyncpg.Connection,
    operation: ExternalOperation,
    *,
    result: dict,
) -> None:
    """Complete an operation inside the caller's entity-write transaction."""
    updated_id = await db.fetchval(
        """UPDATE external_operations
           SET status = 'succeeded', external_result = $2,
               last_error = NULL, updated_at = NOW()
           WHERE id = $1 AND status = 'pending' AND attempt_count = $3
           RETURNING id""",
        operation.id,
        result,
        operation.attempt_count,
    )
    if updated_id is None:
        raise OperationBusy(operation)
    if operation.source_message_id is not None:
        await db.execute(
            ACCEPT_SLOT_SQL,
            operation.source_message_id,
            operation.proposal_slot,
            acceptance_stamp(operation.initiated_by),
        )


async def fail_operation(
    pool: asyncpg.Pool,
    operation: ExternalOperation,
    *,
    error: str,
) -> None:
    """Release a failed operation without holding a connection beyond SQL."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """UPDATE external_operations
                   SET status = 'failed', last_error = $2, updated_at = NOW()
                   WHERE id = $1 AND status = 'pending' AND attempt_count = $3""",
                operation.id,
                error[:500],
                operation.attempt_count,
            )
