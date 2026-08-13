"""
Real-Postgres contracts for House v2 semantic movement (home_activity.py).

WHY real Postgres: every movement kind is a fenced SQL read over a different
source table, and the membership fence is the whole privacy invariant. A mocked
DB would assert the shape of a query that never ran.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/013_home_base.sql
    psql dialectic_test -f migrations/014_reading_library.sql
"""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from home_activity import MOVEMENT_KINDS, HomeActivityService

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO, DAN = _uid(0xE01), _uid(0xE02)
SHARED, SOLO = _uid(0xE11), _uid(0xE12)
TS, TSOLO = _uid(0xE21), _uid(0xE22)
M_RESEARCH, M_CLAIM, M_RESOLVE, M_ECHO, M_SOLO = (
    _uid(0xE31), _uid(0xE32), _uid(0xE33), _uid(0xE34), _uid(0xE35),
)
BASE = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    yield conn
    await conn.close()


async def _msg(db, mid, thread, seq, at, content, metadata=None):
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
               speaker_type, message_type, content, is_deleted, metadata)
           VALUES ($1,$2,$3,$4,'llm_primary','text',$5,false,$6::jsonb)""",
        mid, thread, seq, at, content, metadata,
    )


@pytest_asyncio.fixture
async def moved(db):
    """One shared room carrying all eight movement kinds, plus a solo room
    carrying the same kinds that must never appear for the other member."""
    tx = db.transaction()
    await tx.start()
    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")

    for uid, name in ((AMO, "Amo"), (DAN, "Dan")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
            uid, _d(40), name)
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            home_id, uid, _d(30))

    for rid, nm in ((SHARED, "Shared Scheme"), (SOLO, "Amo Solo")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, _d(30), f"movement-{rid}", nm)
    for uid in (AMO, DAN):
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            SHARED, uid, _d(30))
    await db.execute(
        "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
        SOLO, AMO, _d(30))

    for tid, rid in ((TS, SHARED), (TSOLO, SOLO)):
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            tid, rid, _d(30))

    # reading_filed + wire_interruption
    for rid, tid, src, title in (
        (SHARED, TS, "proposal", "Filed by a human"),
        (SHARED, TS, "wire", "Wire interrupted the room"),
        (SOLO, TSOLO, "proposal", "SOLO-LEAK-SENTINEL"),
    ):
        await db.execute(
            """INSERT INTO reading_items (room_id,url,title,content,summary,source,created_at)
               VALUES ($1,$2,$3,'body','sum',$4,$5)""",
            rid, f"https://example.test/{src}/{rid}", title, src, _d(1))

    # research_completed / claim_warning / prediction_review / echo_created
    await _msg(db, M_RESEARCH, TS, 1, _d(2), "Research brief",
               '{"source":"deep_dive"}')
    await _msg(db, M_CLAIM, TS, 2, _d(2), "Linked claim",
               '{"claim_check":{"url":"https://x.test","verdict":"mixed","note":"n"}}')
    await _msg(db, M_RESOLVE, TS, 3, _d(1), "Resolution proposed",
               '{"resolution_proposal":{"prediction_id":"p1","statement":"s","verdict":"correct","rationale":"r"}}')
    await _msg(db, M_ECHO, TS, 4, _d(1), "Echo note",
               '{"source":"reading_echo"}')
    await _msg(db, M_SOLO, TSOLO, 1, _d(1), "SOLO-LEAK-SENTINEL",
               '{"source":"deep_dive"}')

    # commitment_due
    await db.execute(
        """INSERT INTO commitments (room_id,thread_id,claim,resolution_criteria,
               category,deadline,status)
           VALUES ($1,$2,'Close before CPI','flat','commitment',$3,'active')""",
        SHARED, TS, BASE + timedelta(hours=12))

    # thesis_lifecycle
    await db.execute(
        """INSERT INTO events (id,timestamp,event_type,room_id,thread_id,payload)
           VALUES ($1,$2,'THESIS_CREATED',$3,$4,'{}'::jsonb)""",
        _uid(0xE41), _d(3), SHARED, TS)

    yield SimpleNamespace(db=db, home_id=home_id)
    await tx.rollback()


def _movement(projection):
    return [m for r in projection.rooms for m in r.movement]


@pytest.mark.asyncio
async def test_every_movement_kind_is_projected(moved):
    proj = await HomeActivityService(moved.db).build(DAN)
    kinds = {m.kind for m in _movement(proj)}
    assert kinds == set(MOVEMENT_KINDS), f"missing: {set(MOVEMENT_KINDS) - kinds}"


@pytest.mark.asyncio
async def test_movement_never_exceeds_the_membership_intersection(moved):
    """THE privacy guard. Dan is not in the solo room; nothing from it may
    appear, in any kind, at any depth."""
    proj = await HomeActivityService(moved.db).build(DAN)
    assert all(m.room_id == SHARED for m in _movement(proj))
    assert "SOLO-LEAK-SENTINEL" not in proj.model_dump_json()
    assert "SOLO-LEAK-SENTINEL" not in proj.to_prompt_section()


@pytest.mark.asyncio
async def test_every_destination_is_a_canonical_room_url(moved):
    proj = await HomeActivityService(moved.db).build(DAN)
    items = _movement(proj)
    assert items
    for m in items:
        assert m.destination.startswith(f"/?room={m.room_id}")
        if m.thread_id is not None:
            assert f"thread={m.thread_id}" in m.destination


@pytest.mark.asyncio
async def test_judgment_flag_marks_only_what_a_human_must_answer(moved):
    proj = await HomeActivityService(moved.db).build(DAN)
    by_kind = {m.kind: m for m in _movement(proj)}
    assert by_kind["prediction_review"].requires_judgment is True
    assert by_kind["commitment_due"].requires_judgment is True
    assert by_kind["claim_warning"].requires_judgment is True
    assert by_kind["reading_filed"].requires_judgment is False
    assert by_kind["echo_created"].requires_judgment is False


@pytest.mark.asyncio
async def test_human_house_and_prompt_context_use_one_projection(moved):
    """Spec 5.3: the two consumers must not diverge. Same call, same items."""
    svc = HomeActivityService(moved.db)
    a = await svc.build(DAN)
    b = await svc.build(DAN)
    assert [(m.kind, m.destination) for m in _movement(a)] \
        == [(m.kind, m.destination) for m in _movement(b)]
    section = a.to_prompt_section()
    for m in _movement(a):
        assert m.kind in section


@pytest.mark.asyncio
async def test_movement_sql_fences_every_arm_by_itself(moved):
    """The fence must hold IN THE SQL, not only in the Python that consumes it.

    WHY this exists: the service drops rows for rooms outside the eligible map
    (`bucket is None`), which MASKS a missing JOIN in any single UNION arm. A
    mutation that deleted the fence from one arm left every projection test
    green. This asserts the statement directly, so each arm is on the hook.
    """
    from home_activity import _MOVEMENT_SQL, _MOVEMENT_TOTAL_CAP

    rows = await moved.db.fetch(_MOVEMENT_SQL, [SHARED], _MOVEMENT_TOTAL_CAP)
    assert rows, "fixture produced no movement at all"
    foreign = [r for r in rows if r["room_id"] != SHARED]
    assert not foreign, f"unfenced rows leaked: {[r['kind'] for r in foreign]}"
    # And the solo room's content must be absent by value, not just by id.
    assert all("SOLO-LEAK-SENTINEL" not in (r["title"] or "") for r in rows)
