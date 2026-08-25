"""
Real-Postgres contract for POST /rooms (api.main.create_room).

WHY THIS EXISTS: the endpoint wrote a rooms row, a threads row and two events
rows but ZERO room_memberships — it took no caller identity at all. That is
why `8adcabb7 Trump Tariffs Trading Room` is bound to a live book with 0
members in production (see CLAUDE.md's 2026-08-15 (Home) amendment, and the
sibling fix in api/home.py's `_SPAWN_SCHEME_SQL`, tested in
tests/test_home_scheme_spawn.py). A room nobody belongs to is a room its own
creator cannot reopen.

WHY real Postgres, not a mock: a mocked db can assert an INSERT statement's
TEXT ran without proving the row is actually there afterward, or that the FK
to users survives. This calls the real endpoint function against a real
connection and queries room_memberships back.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from api.auth.dependencies import AuthenticatedUser
from api.main import CreateRoomRequest, create_room
from models import EventType

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


async def _connect() -> asyncpg.Connection:
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"dialectic_test unavailable: {exc}")
    # Mirrors api/main.py's pool init=_init_connection — create_room passes a
    # raw dict for the events.payload jsonb column, which needs the codec the
    # production pool registers at startup. A bare connection has none.
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    return conn


def _caller(user_id: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, email="creator@example.test",
        email_verified=True, display_name="Creator",
    )


@pytest.mark.asyncio
async def test_creator_is_a_member_of_the_room_they_create():
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        creator_id = uuid4()
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, NOW(), $2)",
            creator_id, "Creator",
        )

        response = await create_room(
            CreateRoomRequest(name="Orphan Check"),
            current_user=_caller(creator_id),
            db=conn,
        )

        member = await conn.fetchval(
            "SELECT user_id FROM room_memberships WHERE room_id = $1 AND user_id = $2",
            response.id, creator_id,
        )
        assert member == creator_id, "the creator must be a member of their own room"

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM room_memberships WHERE room_id = $1", response.id,
        )
        assert total == 1, "exactly one membership row — the creator, no more"
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_room_creation_events_use_the_lowercase_enum_value():
    """Sibling of tests/test_home_scheme_spawn.py's test_spawn_writes_both_events
    for the OTHER creation path. This one was already correct — main.py's
    create_room used EventType(...).value from the start, unlike home.py's
    hardcoded SQL literals — but nothing pinned it, so it stayed correct by
    luck rather than by contract."""
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        creator_id = uuid4()
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, NOW(), $2)",
            creator_id, "Creator",
        )

        response = await create_room(
            CreateRoomRequest(name="Casing Check"),
            current_user=_caller(creator_id),
            db=conn,
        )

        kinds = {
            r["event_type"] for r in await conn.fetch(
                "SELECT event_type FROM events WHERE room_id = $1", response.id,
            )
        }
        assert kinds == {EventType.ROOM_CREATED.value, EventType.THREAD_CREATED.value}
        # replay/engine.py matches lowercase literals ("room_created") — an
        # uppercase event_type is silently invisible to replay, not an error.
        assert kinds == {"room_created", "thread_created"}
    finally:
        await tx.rollback()
        await conn.close()
