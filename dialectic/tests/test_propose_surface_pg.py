"""Real-Postgres round trip for the propose surface (§1.11, §5.3, plan
Ruling R2): "Make a move" writes a normal message whose metadata carries a
proposal block, validated server-side (proposal_intake.py) at the message
create door (POST /threads/{thread_id}/messages, api/main.py:send_message).

WHY real Postgres and the real endpoint function: the door's job is
INSERT-then-be-read-by-the-envelope, and the accept step is a real join
(reading_items / commitments / the acceptance stamp). A mocked DB would
prove the validator agrees with itself, not that a human's draft actually
becomes an envelope another room member can accept.

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

import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser
from proposal_envelope import ProposalEnvelopeService

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


class _BorrowedConnection:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> asyncpg.Connection:
        return self.connection

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _BorrowedPool:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection

    def acquire(self) -> _BorrowedConnection:
        return _BorrowedConnection(self.connection)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xC01)  # proposes
DAN = _uid(0xC02)  # accepts — a DIFFERENT room member, per the plan's
                    # own done-criterion ("the OTHER fixture user accepts")
ROOM = _uid(0xC11)
TH = _uid(0xC21)
NOW = datetime.now(timezone.utc)
FUTURE = (NOW + timedelta(days=30)).date().isoformat()


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


@pytest_asyncio.fixture
async def room(db):
    """Two members, one room, one thread — a rollback workroom."""
    tx = db.transaction()
    await tx.start()

    for uid, name in ((AMO, "Amo"), (DAN, "Dan")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,now(),$2)",
            uid, name)
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,now(),$2,$3)",
        ROOM, "propose-surface-room-token", "Scheme Room")
    for uid in (AMO, DAN):
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,now())",
            ROOM, uid)
    await db.execute(
        "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,now(),'Main')",
        TH, ROOM)

    yield db
    await tx.rollback()


def _caller(user_id: UUID, name: str) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, email=f"{name.lower()}@test", email_verified=True,
        display_name=name,
    )


async def _propose(db, *, metadata, content="proposing", user_id=AMO):
    return await main_mod.send_message(
        thread_id=TH,
        request=main_mod.SendMessageRequest(
            content=content, message_type="text", metadata=metadata,
        ),
        token="propose-surface-room-token",
        current_user=_caller(user_id, "Amo"),
        db=db,
    )


# ---------------------------------------------------------------------------
# The door rejects what proposal_intake.py rejects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_unknown_kind_is_rejected_with_422(room):
    with pytest.raises(HTTPException) as exc:
        await _propose(room, metadata={"claim_check": {"url": "https://x.test", "verdict": "mixed", "note": "n"}})
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_resolution_proposal_is_rejected_with_422(room):
    """§5.3: leave resolution proposals to the LLM flow that owns them."""
    with pytest.raises(HTTPException) as exc:
        await _propose(room, metadata={
            "resolution_proposal": {"prediction_id": "p1", "statement": "x", "verdict": "correct"},
        })
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_malformed_payload_is_rejected_with_422(room):
    with pytest.raises(HTTPException) as exc:
        await _propose(room, metadata={
            "proposal": {"statement": "", "confidence": 0.5, "deadline": FUTURE},
        })
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_no_message_lands_when_metadata_is_rejected(room):
    """A 422 must not leave a half-written row — the whole request refuses."""
    before = await room.fetchval("SELECT count(*) FROM messages WHERE thread_id = $1", TH)
    with pytest.raises(HTTPException):
        await _propose(room, metadata={"not_a_real_slot": {}})
    after = await room.fetchval("SELECT count(*) FROM messages WHERE thread_id = $1", TH)
    assert after == before


@pytest.mark.asyncio
async def test_a_client_cannot_self_stamp_acceptance(room):
    """Trust boundary: accepted/accepted_by/accepted_at are stripped, so a
    human cannot mark their own submission accepted at creation time."""
    response = await _propose(room, metadata={
        "proposal": {
            "statement": "Brent over 90", "confidence": 0.6, "deadline": FUTURE,
            "accepted": True, "accepted_by": str(DAN), "accepted_at": NOW.isoformat(),
        },
    })
    stored = await room.fetchval(
        "SELECT metadata FROM messages WHERE id = $1", response.id)
    assert "accepted" not in stored["proposal"]
    envelope = (await ProposalEnvelopeService(room).build(ROOM))[0]
    assert envelope.status == "proposed"
    assert envelope.accepted_by is None


@pytest.mark.asyncio
async def test_an_ordinary_message_with_no_metadata_is_unaffected(room):
    """Sanity: the door's new parameter must not disturb ordinary sends."""
    response = await _propose(room, metadata=None, content="just talking")
    assert response.metadata is None
    envelopes = await ProposalEnvelopeService(room).build(ROOM)
    assert envelopes == []


# ---------------------------------------------------------------------------
# The full round trip — plan §5.3's own done-criterion, driven for real
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compose_then_envelope_then_the_other_user_accepts(room, monkeypatch):
    """compose -> message lands with metadata -> envelope projects it ->
    the OTHER fixture user accepts it -> accepted_by stamps.

    Composing goes through the real message-create door; accepting goes
    through the real relay (api/prediction_relay.py) — the same one the
    LLM-drafted prediction card already uses, proving the envelope, the
    card and acceptance_stamp() work UNCHANGED for a human-authored
    proposal, which is the entire point of §1.11.
    """
    import api.prediction_relay as relay

    posted = []

    async def fake_post(path, json_body=None):
        posted.append(json_body)
        return {"id": "pred-1", **(json_body or {})}

    monkeypatch.setattr(relay.td, "post", fake_post)

    # compose — Amo proposes.
    response = await _propose(room, metadata={
        "proposal": {"statement": "Brent over 90", "confidence": 0.6, "deadline": FUTURE},
    }, content="Worth logging now.")
    assert response.metadata == {
        "proposal": {"statement": "Brent over 90", "confidence": 0.6, "deadline": FUTURE},
    }

    # message lands with metadata — read back from the row itself, not the
    # response object, so this proves the WRITE, not just the return value.
    stored = await room.fetchrow(
        "SELECT content, metadata, user_id, speaker_type FROM messages WHERE id = $1",
        response.id)
    assert stored["content"] == "Worth logging now."
    assert stored["metadata"]["proposal"]["statement"] == "Brent over 90"
    assert stored["user_id"] == AMO
    assert stored["speaker_type"] == "human"

    # envelope projects it.
    before = await ProposalEnvelopeService(room).build(ROOM)
    assert len(before) == 1
    assert before[0].proposal_kind == "prediction_draft"
    assert before[0].status == "proposed"
    assert before[0].source_message_id == response.id
    assert "accept" in before[0].available_actions
    assert before[0].accepted_by is None

    # the OTHER fixture user accepts it — Dan, not Amo.
    await relay.accept_prediction(
        room_id=ROOM,
        request=relay.AcceptPredictionRequest(message_id=response.id),
        token="propose-surface-room-token",
        current_user=_caller(DAN, "Dan"),
        pool=_BorrowedPool(room),
    )
    assert len(posted) == 1

    # accepted_by stamps — the accepting human, not the proposing one.
    after = (await ProposalEnvelopeService(room).build(ROOM))[0]
    assert after.status == "accepted"
    assert after.accepted_by == DAN
    assert after.accepted_at is not None
    assert after.payload["statement"] == "Brent over 90"


@pytest.mark.asyncio
async def test_a_commitment_proposal_round_trips_through_the_ws_accept_path(room):
    """The other three kinds get the same door; commitment_proposal's own
    accept path is the WS create_commitment handler rather than a REST
    relay, so this proves that leg too — the envelope must not care which
    door wrote `accepted`, only that acceptance_stamp() did."""
    from proposal_envelope import ACCEPT_LIST_ITEM_SQL, acceptance_stamp

    response = await _propose(room, metadata={
        "commitment_proposals": [
            {"claim": "I close before CPI", "resolution_criteria": "flat", "category": "bet"},
        ],
    })

    before = (await ProposalEnvelopeService(room).build(ROOM))[0]
    assert before.proposal_kind == "commitment_proposal"
    assert before.status == "proposed"

    # The commitment row itself + the stamp, exactly as
    # transport/handlers.py._handle_create_commitment writes them together.
    commitment_id = _uid(0xC31)
    await room.execute(
        """INSERT INTO commitments (id,room_id,thread_id,source_message_id,claim,
               resolution_criteria,category,status,created_by_user_id,created_at)
           VALUES ($1,$2,$3,$4,'I close before CPI','flat','bet','active',$5,now())""",
        commitment_id, ROOM, TH, response.id, DAN)
    await room.execute(ACCEPT_LIST_ITEM_SQL, response.id, "0", 0, acceptance_stamp(DAN))

    after = (await ProposalEnvelopeService(room).build(ROOM))[0]
    assert after.status == "accepted"
    assert after.accepted_by == DAN
    assert after.target_object == f"commitment:{commitment_id}"
