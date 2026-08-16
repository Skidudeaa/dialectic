"""
Real-Postgres contract for GET /rooms/{room_id}/members.

WHY real Postgres and not a mock: this route exists BECAUSE a roster built
from presence could not see a member who had never spoken and was not
connected (2026-08-16 — the room gained a third human with zero messages, and
the @-mention picker had no way to offer him). The whole value is in what the
JOIN returns for exactly that person, which a mocked `fetch` cannot tell you:
it would happily return whatever list the test handed it, including one the
real query could never produce.

The route function is called directly rather than through TestClient so the
REAL `verify_room_token` runs against a real row — the token check and the
membership join are the two things worth proving.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.main import get_room_members

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, OTHER_ROOM = _uid(0xD01), _uid(0xD02)
AMO, DAN, SCOTT, STRANGER = _uid(0xD11), _uid(0xD12), _uid(0xD13), _uid(0xD14)
TOKEN = "members-route-token"
BASE = datetime(2026, 8, 16, 4, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    """Three members joined in a known order, plus a stranger in another room."""
    tx = db.transaction()
    await tx.start()
    for room_id, token in ((ROOM, TOKEN), (OTHER_ROOM, "other-token")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            room_id, BASE, token, f"room-{room_id}",
        )
    for user_id, name in (
        (AMO, "Amo"), (DAN, "Dan"), (SCOTT, "Scott"), (STRANGER, "Stranger"),
    ):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
            user_id, BASE, name,
        )
    for i, user_id in enumerate((AMO, DAN, SCOTT)):
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
            ROOM, user_id, BASE + timedelta(minutes=i),
        )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        OTHER_ROOM, STRANGER, BASE,
    )
    yield db
    await tx.rollback()


@pytest.mark.asyncio
async def test_returns_every_member_including_the_silent_one(room):
    """Scott has no messages and no presence row — the point of the route."""
    members = await get_room_members(room_id=ROOM, token=TOKEN, db=room)
    assert [m.display_name for m in members] == ["Amo", "Dan", "Scott"]


@pytest.mark.asyncio
async def test_presence_is_not_consulted(room):
    """No user_presence rows exist at all, and the roster is still complete.

    This is the assertion that would have caught the original defect: a
    presence-derived roster returns an empty list here.
    """
    assert await room.fetchval("SELECT count(*) FROM user_presence WHERE room_id=$1", ROOM) == 0
    members = await get_room_members(room_id=ROOM, token=TOKEN, db=room)
    assert len(members) == 3


@pytest.mark.asyncio
async def test_another_rooms_member_never_leaks(room):
    members = await get_room_members(room_id=ROOM, token=TOKEN, db=room)
    assert "Stranger" not in [m.display_name for m in members]


@pytest.mark.asyncio
async def test_a_wrong_token_is_refused_before_any_roster_is_built(room):
    with pytest.raises(HTTPException) as exc:
        await get_room_members(room_id=ROOM, token="not-the-token", db=room)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_the_uuid_binds(room):
    """The route binds a Python UUID into the join.

    A mocked test reads the query TEXT and never discovers a type mismatch;
    only a real execution does.
    """
    members = await get_room_members(room_id=ROOM, token=TOKEN, db=room)
    assert {m.user_id for m in members} == {AMO, DAN, SCOTT}


@pytest.mark.asyncio
async def test_a_room_with_no_memberships_is_empty_not_an_error(room):
    """`POST /rooms` writes zero memberships, so this is a real production
    shape (e.g. the Trump Tariffs room, bound to a live book with 0 members)."""
    members = await get_room_members(room_id=OTHER_ROOM, token="other-token", db=room)
    assert [m.display_name for m in members] == ["Stranger"]
    await room.execute("DELETE FROM room_memberships WHERE room_id=$1", OTHER_ROOM)
    assert await get_room_members(room_id=OTHER_ROOM, token="other-token", db=room) == []
