"""
Real-Postgres contract for POST /rooms/{room_id}/field/marks — the door that
lets a HUMAN originate a Field mark.

WHY this door exists: Release 3 shipped review (confirm/contest/correct/
supersede/split/merge), which all act on a mark the inference engine proposed
first. Production shows the consequence exactly — 85 marks, every one
`origin='inferred'`, zero human reviews ever. A person could correct the
machine's reading and could not assert anything it had not thought of.

WHY real Postgres: two things here are properties of the DATABASE, not of
Python. The ON CONFLICT clause must match a PARTIAL unique index, which
Postgres refuses to infer unless the clause repeats the index's own WHERE —
and it fails by RAISING, not by skipping dedup. And `_subject_token` folds
`field` into the dedup key, which is the whole reason two highlights on
different passages of one message can coexist; nothing but a real insert
proves that.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/017_field_marks.sql
"""

import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.auth.dependencies import AuthenticatedUser
from api.field import FieldMarkCreateRequest, create_field_mark
from field_marks import FieldSubjectRef, compute_dedup_key

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, OTHER_ROOM = _uid(0xA01), _uid(0xA02)
THREAD, OTHER_THREAD = _uid(0xA03), _uid(0xA04)
AMO, STRANGER = _uid(0xA05), _uid(0xA06)
MSG_A, MSG_B, MSG_OTHER = _uid(0xA07), _uid(0xA08), _uid(0xA09)
TOKEN = "field-origination-token"
BASE = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)


def row_id(mark) -> UUID:
    """`FieldMark.id` is the workspace-object form `field_mark:<uuid>`; the
    row's primary key is the bare uuid. Peeling it here rather than in five
    assertions keeps the prefix contract in one place."""
    return UUID(mark.id.split(":", 1)[1])


def caller(user_id=AMO):
    return AuthenticatedUser(
        user_id=user_id, email="amo@example.com",
        email_verified=True, display_name="Amo",
    )


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    if not await conn.fetchval("SELECT to_regclass('field_marks')"):
        await conn.close()
        pytest.skip("field_marks missing — run migrations/017_field_marks.sql")
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
    for room_id, token in ((ROOM, TOKEN), (OTHER_ROOM, "other-token")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            room_id, BASE, token, f"room-{room_id}",
        )
    for thread_id, room_id in ((THREAD, ROOM), (OTHER_THREAD, OTHER_ROOM)):
        await db.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,'Main')",
            thread_id, room_id, BASE,
        )
    for user_id, name in ((AMO, "Amo"), (STRANGER, "Stranger")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
            user_id, BASE, name,
        )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        ROOM, AMO, BASE,
    )
    # (thread_id, sequence) is UNIQUE — two messages in one thread need
    # distinct sequences, which is exactly what production does too.
    for seq, (msg_id, thread_id, content) in enumerate((
        (MSG_A, THREAD, "tanker rates moved before crude did, twice this month"),
        (MSG_B, THREAD, "that is a correlation, not a mechanism"),
        (MSG_OTHER, OTHER_THREAD, "a message in a room the caller cannot see"),
    ), start=1):
        await db.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at,
                   speaker_type, user_id, message_type, content)
               VALUES ($1,$2,$3,$4,'human',$5,'text',$6)""",
            msg_id, thread_id, seq, BASE, AMO, content,
        )
    yield db
    await tx.rollback()


def _request(**overrides):
    body = dict(
        relation="emerging_position",
        subjects=[FieldSubjectRef(entity="messages", id=str(MSG_A))],
        title="tanker rates lead crude",
        payload={},
        thread_id=THREAD,
    )
    body.update(overrides)
    return FieldMarkCreateRequest(**body)


async def _create(db, **overrides):
    return await create_field_mark(
        room_id=overrides.pop("room_id", ROOM),
        request=_request(**overrides),
        token=overrides.pop("token", TOKEN),
        current_user=overrides.pop("current_user", caller()),
        db=db,
    )


@pytest.mark.asyncio
async def test_a_human_can_originate_a_mark(room):
    mark = await _create(room)
    assert mark.origin == "explicit"
    assert mark.title == "tanker rates lead crude"
    assert mark.id.startswith("field_mark:"), "workspace-object id form"
    stored = await room.fetchrow(
        "SELECT origin, provenance, actor_user_id FROM field_marks WHERE id = $1",
        row_id(mark),
    )
    assert stored["origin"] == "explicit"
    assert stored["provenance"] == "human"
    # No mark may be "by nobody" — the same rule acceptance_stamp enforces.
    assert stored["actor_user_id"] == AMO


@pytest.mark.asyncio
async def test_marking_the_same_thing_twice_is_idempotent(room):
    """The ON CONFLICT must MATCH the partial index, not raise against it.

    If the clause omitted `WHERE dedup_key IS NOT NULL`, this call raises
    InvalidColumnReferenceError rather than deduplicating — a double-tap on a
    highlighter would 500.
    """
    first = await _create(room)
    second = await _create(room)
    assert first.id == second.id, "the second call returns the existing mark"
    count = await room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1 AND mark_kind = 'relation'",
        ROOM,
    )
    assert count == 1


@pytest.mark.asyncio
async def test_two_passages_of_one_message_do_not_collide(room):
    """`field` is folded into the dedup key — this is what makes a passage
    highlighter possible at all, since every highlight on a message shares
    its entity and id."""
    a = await _create(room, subjects=[
        FieldSubjectRef(entity="messages", id=str(MSG_A), field="quote:tanker-rates"),
    ])
    b = await _create(room, subjects=[
        FieldSubjectRef(entity="messages", id=str(MSG_A), field="quote:before-crude"),
    ])
    assert a.id != b.id
    assert await room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1 AND mark_kind='relation'", ROOM,
    ) == 2


@pytest.mark.asyncio
async def test_a_subject_in_another_room_fails_closed(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, subjects=[
            FieldSubjectRef(entity="messages", id=str(MSG_OTHER)),
        ])
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_thread_in_another_room_fails_closed(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, thread_id=OTHER_THREAD)
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_relation_outside_the_vocabulary_is_refused(room):
    """FIELD_RELATIONS is the guard; nothing downstream re-checks it."""
    with pytest.raises(HTTPException) as exc:
        await _create(room, relation="meta")
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_non_member_cannot_mark(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, current_user=caller(STRANGER))
    assert exc.value.status_code == 403
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_wrong_room_token_is_refused(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, token="not-the-token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_the_dedup_key_matches_what_inference_would_compute(room):
    """A human's mark and a later inference candidate over the same subjects
    must collide, or the machine re-proposes what a person already asserted."""
    subjects = [{"entity": "messages", "id": str(MSG_A)}]
    mark = await _create(room)
    stored_key = await room.fetchval(
        "SELECT dedup_key FROM field_marks WHERE id = $1", row_id(mark),
    )
    assert stored_key == compute_dedup_key("emerging_position", subjects)


@pytest.mark.asyncio
async def test_the_creation_is_evented(room):
    mark = await _create(room)
    row = await room.fetchrow(
        """SELECT event_type, payload FROM events
           WHERE room_id = $1 AND event_type = 'field_mark_created'""",
        ROOM,
    )
    assert row is not None
    assert row["payload"]["mark_id"] == str(row_id(mark))
    assert row["payload"]["origin"] == "explicit"
