"""
Home Base schema foundation: migration 013, the founder-activation script,
and the model fields — plus real-Postgres idempotency proof.

WHY real Postgres: the singleton invariant lives in a partial unique index
and the bootstrap lives in a DO block — a mocked DB would test nothing.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from models import EventType, Room, RoomMembership

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    yield conn
    await conn.close()


def test_home_schema_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = (root / "schema.sql").read_text()
    migration = (root / "migrations" / "013_home_base.sql").read_text()
    activation = (root / "deploy" / "activate_home_founders.sql").read_text()

    for sql in (schema, migration):
        assert "is_home BOOLEAN NOT NULL DEFAULT FALSE" in sql
        assert "can_manage_home BOOLEAN NOT NULL DEFAULT FALSE" in sql
        assert "WHERE is_home" in sql

    assert f"'{EventType.ROOM_CREATED.value}'" in migration
    assert f"'{EventType.THREAD_CREATED.value}'" in migration
    assert f"'{EventType.USER_JOINED_ROOM.value}'" in activation

    assert ":'amo_email'" in activation
    assert ":'dan_email'" in activation
    assert "display_name" not in activation
    assert "can_manage_home = TRUE" in activation
    assert Room.model_fields["is_home"].default is False
    assert RoomMembership.model_fields["can_manage_home"].default is False


@pytest.mark.asyncio
async def test_migration_013_is_idempotent(db) -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "013_home_base.sql"
    ).read_text()
    tx = db.transaction()
    await tx.start()
    try:
        await db.execute(migration)
        await db.execute(migration)
        home_id = await db.fetchval(
            "SELECT id FROM rooms WHERE is_home"
        )
        assert home_id is not None
        assert await db.fetchval(
            "SELECT count(*) FROM rooms WHERE is_home"
        ) == 1
        assert await db.fetchval(
            """SELECT count(*) FROM threads
               WHERE room_id = $1 AND parent_thread_id IS NULL""",
            home_id,
        ) == 1
        assert await db.fetchval(
            """SELECT count(*) FROM events
               WHERE room_id = $1 AND event_type = $2""",
            home_id, EventType.ROOM_CREATED.value,
        ) == 1
        assert await db.fetchval(
            """SELECT count(*) FROM events
               WHERE room_id = $1 AND event_type = $2""",
            home_id, EventType.THREAD_CREATED.value,
        ) == 1
        assert await db.fetchval(
            "SELECT count(*) FROM room_memberships WHERE room_id = $1",
            home_id,
        ) == 0
    finally:
        await tx.rollback()
