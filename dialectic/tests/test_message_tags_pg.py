"""
Real-Postgres contract for message tags: the gate, the storage, the retrieval.

WHY real Postgres: the retrieval hangs on `m.metadata->'tags' ? $n`, the JSONB
key-exists operator, executed through asyncpg with a bound parameter. Reading
that query in a mocked test proves nothing — an operator the driver mishandles
or a jsonb/text mismatch fails at BIND time, on the first real call, which in
this case is the first time anyone tries to find their own bug reports.

The tag exists so product-meta stops evaporating ("a tag or marker ... so we
don't lose track of them"), which makes retrieval the whole feature. A tag
that stores but cannot be searched is decoration.

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

from proposal_intake import MESSAGE_TAGS

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, THREAD, AMO = _uid(0xE01), _uid(0xE02), _uid(0xE03)
BASE = datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc)

# (tags, content) — the shapes a room actually produces.
SEEDS = [
    (["bug"], "the mention chips render behind the fold on iPad"),
    (["meta"], "should the Field own product notes or should tags"),
    (["bug", "idea"], "push is broken, and maybe we want digest mode"),
    (None, "an ordinary message carrying no tags at all"),
    ([], "explicitly empty, which the gate refuses but the DB could hold"),
]


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
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        ROOM, BASE, uuid4().hex, "Tag Room",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        THREAD, ROOM, BASE, "Main",
    )
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
        AMO, BASE, "Amo",
    )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        ROOM, AMO, BASE,
    )
    for i, (tags, content) in enumerate(SEEDS):
        await db.execute(
            """INSERT INTO messages
                   (id, thread_id, sequence, created_at, speaker_type, user_id,
                    message_type, content, metadata)
               VALUES ($1,$2,$3,$4,'human',$5,'text',$6,$7)""",
            uuid4(), THREAD, i + 1, BASE + timedelta(minutes=i), AMO, content,
            {"tags": tags} if tags is not None else None,
        )
    yield db
    await tx.rollback()


# The retrieval predicate, written ONCE here the way the route writes it, so
# a drift between them shows up as a failing test rather than an empty result.
TAG_SQL = """
    SELECT m.content FROM messages m
    JOIN threads t ON t.id = m.thread_id
    JOIN room_memberships rm ON rm.room_id = t.room_id
    WHERE rm.user_id = $1 AND t.room_id = $2
      AND m.metadata->'tags' ? $3
      AND NOT m.is_deleted
    ORDER BY m.created_at DESC
"""


@pytest.mark.asyncio
async def test_the_jsonb_key_exists_operator_binds(room):
    """The whole reason this file exists: `?` with a bound parameter."""
    rows = await room.fetch(TAG_SQL, AMO, ROOM, "bug")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_a_message_with_two_tags_is_found_under_each(room):
    both = "push is broken, and maybe we want digest mode"
    for tag in ("bug", "idea"):
        contents = [r["content"] for r in await room.fetch(TAG_SQL, AMO, ROOM, tag)]
        assert both in contents, tag


@pytest.mark.asyncio
async def test_untagged_messages_never_match(room):
    for tag in MESSAGE_TAGS:
        contents = [r["content"] for r in await room.fetch(TAG_SQL, AMO, ROOM, tag)]
        assert "an ordinary message carrying no tags at all" not in contents
        assert "explicitly empty, which the gate refuses but the DB could hold" not in contents


@pytest.mark.asyncio
async def test_a_tag_nobody_used_returns_empty_rather_than_erroring(room):
    assert await room.fetch(TAG_SQL, AMO, ROOM, "idea")
    await room.execute("DELETE FROM messages WHERE metadata->'tags' ? 'idea'")
    assert await room.fetch(TAG_SQL, AMO, ROOM, "idea") == []


@pytest.mark.asyncio
async def test_membership_fences_the_search(room):
    """A caller who is not a member matches nothing, by the join alone."""
    stranger = _uid(0xE09)
    await room.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
        stranger, BASE, "Stranger",
    )
    assert await room.fetch(TAG_SQL, stranger, ROOM, "bug") == []


@pytest.mark.asyncio
async def test_tags_survive_the_jsonb_round_trip_as_a_list(room):
    """Stored as a JSON array, not a string — `?` would silently miss a string."""
    stored = await room.fetchval(
        "SELECT metadata->'tags' FROM messages WHERE content LIKE 'the mention chips%'"
    )
    assert stored == ["bug"]
    assert isinstance(stored, list)


# ── The REAL route, not a re-derivation of its predicate ──────────────
#
# Everything above proves the operator works. It does NOT prove the route
# uses it correctly, because it writes its own copy of the query — the same
# trap as a verification check that re-implements the rule it verifies. The
# tests below call api.main.search_messages itself.

@pytest.mark.asyncio
async def test_the_route_finds_tagged_messages(room):
    from api.main import search_messages
    from api.auth.dependencies import AuthenticatedUser

    caller = AuthenticatedUser(
        user_id=AMO, email="amo@example.com", email_verified=True, display_name="Amo",
    )
    results = await search_messages(
        q=None, tag="bug", room_id=ROOM, thread_id=None, date_from=None,
        date_to=None, speaker_type=None, limit=50,
        token="unused-here", current_user=caller, db=room,
    )
    assert len(results) == 2
    assert all(r.snippet for r in results), "a tag-only search still returns an excerpt"


@pytest.mark.asyncio
async def test_the_route_refuses_a_search_with_neither_q_nor_tag(room):
    """An unfiltered dump of every message the caller can see is not a search."""
    from fastapi import HTTPException
    from api.main import search_messages
    from api.auth.dependencies import AuthenticatedUser

    caller = AuthenticatedUser(
        user_id=AMO, email="amo@example.com", email_verified=True, display_name="Amo",
    )
    with pytest.raises(HTTPException) as exc:
        await search_messages(
            q=None, tag=None, room_id=ROOM, thread_id=None, date_from=None,
            date_to=None, speaker_type=None, limit=50,
            token="unused-here", current_user=caller, db=room,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_the_route_refuses_a_tag_outside_the_vocabulary(room):
    from fastapi import HTTPException
    from api.main import search_messages
    from api.auth.dependencies import AuthenticatedUser

    caller = AuthenticatedUser(
        user_id=AMO, email="amo@example.com", email_verified=True, display_name="Amo",
    )
    with pytest.raises(HTTPException) as exc:
        await search_messages(
            q=None, tag="wishlist", room_id=ROOM, thread_id=None, date_from=None,
            date_to=None, speaker_type=None, limit=50,
            token="unused-here", current_user=caller, db=room,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_text_search_still_works_untouched(room):
    """`q` becoming optional must not have broken the ordinary path."""
    from api.main import search_messages
    from api.auth.dependencies import AuthenticatedUser

    caller = AuthenticatedUser(
        user_id=AMO, email="amo@example.com", email_verified=True, display_name="Amo",
    )
    results = await search_messages(
        q="mention chips", tag=None, room_id=ROOM, thread_id=None, date_from=None,
        date_to=None, speaker_type=None, limit=50,
        token="unused-here", current_user=caller, db=room,
    )
    assert results and "<mark>" in results[0].snippet, "headline highlighting intact"


@pytest.mark.asyncio
async def test_q_and_tag_together_narrow_each_other(room):
    from api.main import search_messages
    from api.auth.dependencies import AuthenticatedUser

    caller = AuthenticatedUser(
        user_id=AMO, email="amo@example.com", email_verified=True, display_name="Amo",
    )
    results = await search_messages(
        q="push", tag="bug", room_id=ROOM, thread_id=None, date_from=None,
        date_to=None, speaker_type=None, limit=50,
        token="unused-here", current_user=caller, db=room,
    )
    assert len(results) == 1
    assert "push is broken" in results[0].content
