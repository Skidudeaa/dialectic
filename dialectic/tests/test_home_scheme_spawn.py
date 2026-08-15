# tests/test_home_scheme_spawn.py — Home can open the scheme's room
"""
WHY THIS FILE: Home refuses to bind a thesis (thesis_relay answers 409) and has
no Bench, so tapping a proposed thesis there resolved to the default scene and
did nothing. General talk that turned into work hit a wall and left the room —
the exact failure the shared room was created to prevent.

The fix spawns the scheme's room from Home. The load-bearing part is the
MEMBERSHIP: `POST /rooms` writes zero room_memberships (it takes no caller
identity at all), which is why a bound trading room with 0 members already
exists in production. A spawned room nobody belongs to is a room neither of
them can open.

These run against real Postgres because the route sends a raw multi-CTE
statement with UUID and jsonb parameters. A mocked test can only assert the
query's TEXT, which never binds anything — the one thing that cannot catch a
wrong cast or a broken join is the thing that reads the SQL without running it.
Skips cleanly when dialectic_test is absent.
"""
import json
import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

asyncpg = pytest.importorskip("asyncpg")

from api.home import _SPAWN_SCHEME_SQL  # noqa: E402
from api.thread_titles import ROOT_THREAD_TITLE  # noqa: E402

TEST_DSN = os.getenv("TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test")


async def _connect():
    try:
        return await asyncpg.connect(TEST_DSN)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"dialectic_test unavailable: {exc}")


async def _spawn(conn, caller, name="Drillers"):
    return await conn.fetchrow(
        _SPAWN_SCHEME_SQL,
        caller,
        uuid4(),
        uuid4().hex,
        name,
        uuid4(),
        ROOT_THREAD_TITLE,
        uuid4(),
        json.dumps({"name": name, "spawned_from": "home"}),
        uuid4(),
        json.dumps({"title": ROOT_THREAD_TITLE}),
    )


async def _seed_home(conn, member_count=2):
    """`member_count` fresh members of THE Home room. Caller rolls back.

    Reuses the existing Home rather than creating one: `idx_rooms_single_home`
    is a partial unique index on is_home, so a second Home is not merely
    untidy, it is impossible — and a fixture that invented one would be
    testing a shape the database refuses. Any pre-existing members are cleared
    inside the transaction so the carried count is exactly what we seeded.
    """
    home_id = await conn.fetchval("SELECT id FROM rooms WHERE is_home LIMIT 1")
    if home_id is None:
        home_id = uuid4()
        await conn.execute(
            "INSERT INTO rooms (id, created_at, token, name, is_home) "
            "VALUES ($1, NOW(), $2, 'Home', TRUE)",
            home_id, uuid4().hex,
        )
    await conn.execute("DELETE FROM room_memberships WHERE room_id = $1", home_id)
    members = []
    for i in range(member_count):
        uid = uuid4()
        # Only the columns the schema.sql baseline guarantees — dialectic_test
        # is built from that baseline and predates the auth migrations, so it
        # has no users.email. Nothing here needs one.
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, NOW(), $2)",
            uid, f"member{i}",
        )
        await conn.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at, can_manage_home) "
            "VALUES ($1, $2, NOW(), TRUE)",
            home_id, uid,
        )
        members.append(uid)
    return home_id, members


async def test_spawn_carries_every_home_member():
    """The regression this endpoint exists to prevent: a room with no members."""
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        _, members = await _seed_home(conn, member_count=2)
        row = await _spawn(conn, members[0])

        assert row is not None and row["room_id"] is not None
        assert row["member_count"] == 2

        # Assert the ROWS, not the reported count — the count could be right
        # while the insert wrote nothing the join can see.
        written = await conn.fetchval(
            "SELECT COUNT(*) FROM room_memberships WHERE room_id = $1", row["room_id"],
        )
        assert written == 2, "the spawned room must not be one nobody can open"

        seeded = {str(m) for m in members}
        got = {
            str(r["user_id"]) for r in await conn.fetch(
                "SELECT user_id FROM room_memberships WHERE room_id = $1", row["room_id"],
            )
        }
        assert got == seeded, "the OTHER person must be carried, not just the caller"
    finally:
        await tx.rollback()
        await conn.close()


async def test_spawn_never_delegates_home_capability():
    """can_manage_home is Home's and nondelegable; an ordinary room has no use
    for it. Home's own members carry it TRUE — the spawn must not copy that."""
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        _, members = await _seed_home(conn)
        row = await _spawn(conn, members[0])
        leaked = await conn.fetchval(
            "SELECT bool_or(can_manage_home) FROM room_memberships WHERE room_id = $1",
            row["room_id"],
        )
        assert leaked is False
    finally:
        await tx.rollback()
        await conn.close()


async def test_non_member_creates_nothing():
    """Authorization lives IN the statement — the CTE's first term joins the
    caller's membership, so a stranger matches no Home and every downstream
    insert writes zero rows. Assert the absence of the ROOM, not just the
    absence of a return value."""
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        await _seed_home(conn)
        stranger = uuid4()
        row = await _spawn(conn, stranger, name="Trespass")

        assert row is None or row["room_id"] is None
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM rooms WHERE name = 'Trespass'"
        ) == 0
    finally:
        await tx.rollback()
        await conn.close()


async def test_spawned_room_gets_a_named_root_thread():
    """Not "Main". The label the owner could not identify came from a literal
    written in two places; both now read one constant."""
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        _, members = await _seed_home(conn)
        row = await _spawn(conn, members[0])
        title = await conn.fetchval(
            "SELECT title FROM threads WHERE id = $1", row["thread_id"],
        )
        assert title == ROOT_THREAD_TITLE
        assert title != "Main"
    finally:
        await tx.rollback()
        await conn.close()


async def test_spawn_writes_both_events():
    """Event sourcing is the source of truth — a room that appears without a
    ROOM_CREATED event is a room the log cannot explain."""
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        _, members = await _seed_home(conn)
        row = await _spawn(conn, members[0])
        kinds = {
            r["event_type"] for r in await conn.fetch(
                "SELECT event_type FROM events WHERE room_id = $1", row["room_id"],
            )
        }
        assert kinds == {"ROOM_CREATED", "THREAD_CREATED"}
    finally:
        await tx.rollback()
        await conn.close()
