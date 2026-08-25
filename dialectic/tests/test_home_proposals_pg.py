"""
Real-Postgres contracts for the cross-room proposal inbox (api/home_proposals.py).

WHY real Postgres: room selection and per-room normalization are each
already proven elsewhere (home_activity.py's membership intersection,
proposal_envelope.py's status derivation) — what is new here is the WIRING
between them, and a mock cannot show whether this endpoint's room ids
actually reach build_proposal_projection or whether a nonmember gets the
same 404 shape the sibling activity endpoint gives.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/013_home_base.sql
    psql dialectic_test -f migrations/014_reading_library.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.auth.dependencies import AuthenticatedUser
from api.home_proposals import get_home_proposals

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xE01)
DAN = _uid(0xE02)
NONMEMBER = _uid(0xE03)
ROOM_A, ROOM_B = _uid(0xE11), _uid(0xE12)
TH_A, TH_B = _uid(0xE21), _uid(0xE22)
M_A, M_B = _uid(0xE31), _uid(0xE32)
NOW = datetime.now(timezone.utc)
FUTURE = (NOW + timedelta(days=30)).date().isoformat()


def _caller(user_id: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, email=f"{user_id}@test", email_verified=True,
        display_name="Tester",
    )


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


async def _msg(db, mid, thread, seq, metadata, *, at):
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
               speaker_type, user_id, message_type, content, is_deleted, metadata)
           VALUES ($1,$2,$3,$4,'llm_primary',NULL,'text','carrier',false,$5)""",
        mid, thread, seq, at, metadata,
    )


@pytest_asyncio.fixture
async def scenario(db):
    """Two Home members (Amo, Dan) sharing two scheme rooms, each carrying
    one pending proposal. NONMEMBER belongs to neither Home nor either room.
    """
    tx = db.transaction()
    await tx.start()

    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    assert home_id is not None

    for uid, name in ((AMO, "Amo"), (DAN, "Dan"), (NONMEMBER, "Nonmember")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, now(), $2)",
            uid, name,
        )
    for uid in (AMO, DAN):
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, now())",
            home_id, uid,
        )

    for rid, name in ((ROOM_A, "Room Alpha"), (ROOM_B, "Room Beta")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, now(), $2, $3)",
            rid, f"home-proposals-{rid}", name,
        )
        for uid in (AMO, DAN):
            await db.execute(
                "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, now())",
                rid, uid,
            )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, now(), 'Main')",
        TH_A, ROOM_A,
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, now(), 'Main')",
        TH_B, ROOM_B,
    )

    # Room Alpha's proposal is OLDER; Room Beta's is NEWER — proves sort order.
    await _msg(db, M_A, TH_A, 1, {
        "proposal": {"statement": "Brent over 90", "confidence": 0.6,
                     "deadline": FUTURE, "accepted": False},
    }, at=NOW - timedelta(hours=2))
    await _msg(db, M_B, TH_B, 1, {
        "proposal": {"statement": "XOP above 150", "confidence": 0.55,
                     "deadline": FUTURE, "accepted": False},
    }, at=NOW - timedelta(hours=1))

    yield db
    await tx.rollback()


@pytest.mark.asyncio
async def test_sees_proposals_from_both_shared_rooms_labeled_by_room(scenario):
    response = await get_home_proposals(current_user=_caller(AMO), db=scenario)
    by_room = {p.room_name: p for p in response.proposals}
    assert by_room.keys() == {"Room Alpha", "Room Beta"}
    assert by_room["Room Alpha"].room_id == ROOM_A
    assert by_room["Room Beta"].room_id == ROOM_B
    assert all(p.status == "proposed" for p in response.proposals)
    assert all("accept" in p.available_actions for p in response.proposals)
    assert by_room["Room Alpha"].payload["statement"] == "Brent over 90"


@pytest.mark.asyncio
async def test_pending_proposals_sort_newest_first(scenario):
    response = await get_home_proposals(current_user=_caller(DAN), db=scenario)
    assert [p.room_name for p in response.proposals] == ["Room Beta", "Room Alpha"]


@pytest.mark.asyncio
async def test_accepted_proposal_sorts_behind_a_pending_one_regardless_of_age(scenario):
    """The needs-a-human-now group must outrank recency, not just break ties
    with it -- accept the NEWER proposal and the OLDER pending one must still
    lead."""
    await scenario.execute(
        """UPDATE messages SET metadata = jsonb_set(
               metadata, '{proposal,accepted}', 'true'::jsonb)
           WHERE id = $1""",
        M_B,
    )
    response = await get_home_proposals(current_user=_caller(AMO), db=scenario)
    assert [p.room_name for p in response.proposals] == ["Room Alpha", "Room Beta"]
    assert response.proposals[0].status == "proposed"
    assert response.proposals[1].status == "accepted"


@pytest.mark.asyncio
async def test_nonmember_gets_404_not_a_leak(scenario):
    with pytest.raises(HTTPException) as exc_info:
        await get_home_proposals(current_user=_caller(NONMEMBER), db=scenario)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_home_member_with_no_shared_rooms_gets_empty_not_404(db):
    """Belonging to Home but to no scheme room yet is a valid, empty state —
    not the same 404 as not being a Home member at all."""
    tx = db.transaction()
    await tx.start()
    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    solo = _uid(0xE99)
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1, now(), 'Solo')",
        solo,
    )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, now())",
        home_id, solo,
    )

    response = await get_home_proposals(current_user=_caller(solo), db=db)
    assert response.proposals == []
    await tx.rollback()


@pytest.mark.asyncio
async def test_nonmember_outside_a_transaction_opens_its_own_snapshot(db):
    """On a bare connection (no test-fixture rollback transaction wrapping
    it) the endpoint must still open its own read-only snapshot and still
    answer 404 for a non-Home caller -- proves the is_in_transaction()
    branch that scenario-based tests above never exercise."""
    assert not db.is_in_transaction()
    with pytest.raises(HTTPException) as exc_info:
        await get_home_proposals(current_user=_caller(_uid(0xEFF)), db=db)
    assert exc_info.value.status_code == 404
