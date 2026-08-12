"""
Home Base schema foundation: migration 013, the founder-activation script,
and the model fields — plus real-Postgres idempotency proof.

WHY real Postgres: the singleton invariant lives in a partial unique index
and the bootstrap lives in a DO block — a mocked DB would test nothing.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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


def test_remove_home_member_script_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy" / "remove_home_member.sql").read_text()

    assert f"'{EventType.HOME_MEMBER_REMOVED.value}'" in script
    assert ":'member_email'" in script
    assert ":'removed_by_email'" in script
    # The guards, anchored on the errors they raise.
    assert "Remover must be a current Home manager" in script
    assert "final Home manager" in script
    assert EventType.HOME_MEMBER_REMOVED.value == "home_member_removed"


# The exact membership-intersection shape Task 4's projection enforces:
# a room is eligible only when EVERY current Home member belongs to it.
# $1 = viewer user id, $2 = home room id.
INTERSECTION_SQL = """
    SELECT r.id
    FROM rooms r
    JOIN room_memberships viewer_rm
      ON viewer_rm.room_id = r.id AND viewer_rm.user_id = $1
    WHERE NOT r.is_home
      AND NOT EXISTS (
          SELECT 1
          FROM room_memberships hm
          WHERE hm.room_id = $2
            AND NOT EXISTS (
                SELECT 1
                FROM room_memberships source_rm
                WHERE source_rm.room_id = r.id
                  AND source_rm.user_id = hm.user_id
            )
      )
"""


@pytest.mark.asyncio
async def test_remove_home_member_script_rehearsal(db) -> None:
    """
    Commits real fixtures to dialectic_test, drives psql, and cleans up.

    Proves: the guards refuse a nonmanager remover and the final manager;
    the reviewed removal deletes the membership, appends home_member_removed
    carrying the remover in payload, and re-opens the membership
    intersection for the remaining members.
    """
    root = Path(__file__).resolve().parents[1]
    script = root / "deploy" / "remove_home_member.sql"
    remover_id, target_id, source_room_id = uuid4(), uuid4(), uuid4()
    suffix = uuid4().hex[:12]
    remover_email = f"home-rm-remover-{suffix}@test.local"
    target_email = f"home-rm-target-{suffix}@test.local"
    now = datetime.now(timezone.utc)

    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    assert home_id is not None

    def run_script(member: str, removed_by: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "psql", TEST_DATABASE_URL,
                "-v", f"member_email={member}",
                "-v", f"removed_by_email={removed_by}",
                "-f", str(script),
            ],
            capture_output=True, text=True,
        )

    try:
        for uid, name, email in (
            (remover_id, "Rehearsal Remover", remover_email),
            (target_id, "Rehearsal Target", target_email),
        ):
            await db.execute(
                "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, $3)",
                uid, now, name,
            )
            await db.execute(
                "INSERT INTO user_credentials (user_id, email, password_hash)"
                " VALUES ($1, $2, 'x')",
                uid, email,
            )
        await db.execute(
            """INSERT INTO room_memberships (room_id, user_id, joined_at, can_manage_home)
               VALUES ($1, $2, $3, TRUE), ($1, $4, $3, FALSE)""",
            home_id, remover_id, now, target_id,
        )
        await db.execute(
            "INSERT INTO rooms (id, created_at, token) VALUES ($1, $2, $3)",
            source_room_id, now, f"rehearsal-{suffix}",
        )
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            source_room_id, remover_id, now,
        )

        # Excluded while the target (a Home member) is not in the source room.
        eligible = await db.fetch(INTERSECTION_SQL, remover_id, home_id)
        assert source_room_id not in {r["id"] for r in eligible}

        refused = run_script(remover_email, target_email)
        assert refused.returncode != 0
        assert "Remover must be a current Home manager" in refused.stderr

        refused = run_script(remover_email, remover_email)
        assert refused.returncode != 0
        assert "final Home manager" in refused.stderr

        removed = run_script(target_email, remover_email)
        assert removed.returncode == 0, removed.stderr

        assert await db.fetchval(
            "SELECT count(*) FROM room_memberships WHERE room_id = $1 AND user_id = $2",
            home_id, target_id,
        ) == 0
        event = await db.fetchrow(
            """SELECT payload FROM events
               WHERE room_id = $1 AND user_id = $2 AND event_type = $3""",
            home_id, target_id, EventType.HOME_MEMBER_REMOVED.value,
        )
        assert event is not None
        assert str(remover_id) in str(event["payload"])

        eligible = await db.fetch(INTERSECTION_SQL, remover_id, home_id)
        assert source_room_id in {r["id"] for r in eligible}
    finally:
        await db.execute(
            "DELETE FROM events WHERE user_id IN ($1, $2)", remover_id, target_id
        )
        await db.execute(
            "DELETE FROM room_memberships WHERE user_id IN ($1, $2)",
            remover_id, target_id,
        )
        await db.execute("DELETE FROM rooms WHERE id = $1", source_room_id)
        await db.execute(
            "DELETE FROM user_credentials WHERE user_id IN ($1, $2)",
            remover_id, target_id,
        )
        await db.execute(
            "DELETE FROM users WHERE id IN ($1, $2)", remover_id, target_id
        )
        assert await db.fetchval(
            """SELECT count(*) FROM room_memberships rm
               JOIN rooms r ON r.id = rm.room_id WHERE r.is_home"""
        ) == 0


@pytest.mark.asyncio
async def test_add_member_statement_binds_the_routes_real_types(db) -> None:
    """
    Execute api.home's actual add statement with the exact parameter types
    the route passes (UUIDs, not strings). The mocked API tests assert this
    SQL's text; only real Postgres can prove its bindings — the gate run
    caught $3::text refusing the route's UUID (asyncpg DataError).
    """
    from api.home import _ADD_MEMBER_SQL

    tx = db.transaction()
    await tx.start()
    try:
        home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
        caller_id, target_id = uuid4(), uuid4()
        email = f"add-binding-{uuid4().hex[:10]}@test.local"
        for uid, name in ((caller_id, "Binding Caller"), (target_id, "Binding Target")):
            await db.execute(
                "INSERT INTO users (id, created_at, display_name) VALUES ($1, NOW(), $2)",
                uid, name,
            )
        await db.execute(
            "INSERT INTO user_credentials (user_id, email, password_hash) VALUES ($1, $2, 'x')",
            target_id, email,
        )

        row = await db.fetchrow(_ADD_MEMBER_SQL, home_id, email, caller_id, target_id)
        assert row is not None and row["added"] is True

        assert await db.fetchval(
            "SELECT count(*) FROM room_memberships WHERE room_id = $1 AND user_id = $2 AND NOT can_manage_home",
            home_id, target_id,
        ) == 1
        payload = await db.fetchval(
            """SELECT payload FROM events
               WHERE room_id = $1 AND user_id = $2 AND event_type = 'user_joined'""",
            home_id, target_id,
        )
        assert str(caller_id) in str(payload)

        # Idempotent repeat: no second membership, no second event.
        again = await db.fetchrow(_ADD_MEMBER_SQL, home_id, email, caller_id, target_id)
        assert again["added"] is False
        assert await db.fetchval(
            "SELECT count(*) FROM events WHERE room_id = $1 AND user_id = $2 AND event_type = 'user_joined'",
            home_id, target_id,
        ) == 1
    finally:
        await tx.rollback()
