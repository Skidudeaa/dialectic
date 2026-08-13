"""
Real-Postgres contracts for the unified proposal envelope (proposal_envelope.py).

WHY real Postgres: the envelope's whole job is to normalize proposals that
ALREADY live in message metadata, and to derive a status from the rest of the
room — a filed reading, a bound book, a passed deadline. Every one of those is
a join. A mocked DB would assert the shape of a query that never ran.

WHY the relay is driven for real in the duplicate-disarming test: D3 asks
whether idempotency still holds THROUGH the envelope. Stamping the flag by
hand would prove only that the envelope agrees with my copy of the relay's
rule. It has to be the relay's own write.

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

from proposal_envelope import (
    PROPOSAL_ACTIONS,
    PROPOSAL_KINDS,
    PROPOSAL_SLOTS,
    PROPOSAL_STATUSES,
    ProposalEnvelopeService,
)

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xD01)
ROOM, OTHER = _uid(0xD11), _uid(0xD12)
TH, TH_OTHER = _uid(0xD21), _uid(0xD22)
M_DRAFTS, M_RESOLVE, M_CLAIM, M_OTHER = (
    _uid(0xD31), _uid(0xD32), _uid(0xD33), _uid(0xD34),
)
NOW = datetime.now(timezone.utc)
FUTURE = (NOW + timedelta(days=30)).date().isoformat()
PAST = (NOW - timedelta(days=30)).date().isoformat()
DRAFT_URL = "https://example.test/drafted-reading"


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


async def _msg(db, mid, thread, seq, metadata, content="carrier",
               speaker="llm_primary", user_id=None, at=None):
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
               speaker_type, user_id, message_type, content, is_deleted, metadata)
           VALUES ($1,$2,$3,$4,$5,$6,'text',$7,false,$8)""",
        mid, thread, seq, at or (NOW - timedelta(hours=1)),
        speaker, user_id, content, metadata,
    )


@pytest_asyncio.fixture
async def proposed(db):
    """Every stored proposal shape, exactly as the relays write them today."""
    tx = db.transaction()
    await tx.start()

    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,now(),'Amo')",
        AMO)
    for rid, nm in ((ROOM, "Scheme Room"), (OTHER, "Other Room")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,now(),$2,$3)",
            rid, f"envelope-{rid}", nm)
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,now())",
            rid, AMO)
    for tid, rid in ((TH, ROOM), (TH_OTHER, OTHER)):
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,now(),'Main')",
            tid, rid)

    # Four slots on one message — today's exact hoisted shapes.
    await _msg(db, M_DRAFTS, TH, 1, {
        "proposal": {"statement": "Brent over 90", "confidence": 0.6,
                     "deadline": FUTURE, "accepted": False},
        "thesis_proposal": {"title": "Strait risk", "claim": "the strait shuts",
                            "monthly_budget": 5000},
        "reading_proposal": {"url": DRAFT_URL, "title": "Drafted reading",
                             "summary": "what it argues", "accepted": False},
        "commitment_proposals": [
            {"claim": "I close before CPI", "resolution_criteria": "flat",
             "category": "commitment", "accepted": False},
        ],
    })
    # The annotator's resolution card, on its own message.
    await _msg(db, M_RESOLVE, TH, 2, {
        "source": "prediction_watch",
        "resolution_proposal": {
            "prediction_id": "p1", "statement": "Brent over 90",
            "verdict": "correct", "rationale": "settled above 90 all week",
            "evidence": [{"url": "https://e.test", "title": "E"}],
            "accepted": False,
        },
    })
    # A claim-check badge: NOT a proposal. It must survive untouched.
    await _msg(db, M_CLAIM, TH, 3, {
        "claim_check": {"url": "https://x.test", "verdict": "mixed",
                        "note": "the article says less than the message"},
    }, content="a linked claim", speaker="human", user_id=AMO)
    # The other room's proposal, sentinel-marked.
    await _msg(db, M_OTHER, TH_OTHER, 1, {
        "proposal": {"statement": "OTHER-ROOM-SENTINEL", "confidence": 0.5,
                     "deadline": FUTURE, "accepted": False},
    })

    yield db
    await tx.rollback()


async def _ok(value):
    """An awaitable stand-in for td.post — the desk is not in this test."""
    return value


def _by_kind(envelopes):
    return {e.proposal_kind: e for e in envelopes}


# ---------------------------------------------------------------------------
# D1 — one contract over what is already stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_stored_proposal_shape_normalizes(proposed):
    envelopes = await ProposalEnvelopeService(proposed).build(ROOM)
    kinds = {e.proposal_kind for e in envelopes}
    assert kinds == {
        "prediction_draft", "thesis_proposal", "reading_draft",
        "commitment_proposal", "prediction_resolution",
    }, kinds
    for e in envelopes:
        assert e.proposal_kind in PROPOSAL_KINDS
        assert e.status in PROPOSAL_STATUSES
        assert e.room_id == ROOM
        assert e.branch_id == TH
        assert e.source_message_id in (M_DRAFTS, M_RESOLVE)
        assert e.payload, f"{e.proposal_kind} lost its payload"
        for action in e.available_actions:
            assert action in PROPOSAL_ACTIONS


@pytest.mark.asyncio
async def test_thesis_draft_is_named_but_nothing_stores_it(proposed):
    """The plan lists six kinds; only five have a slot in the database.

    A thesis DRAFT lives in the Create Thesis panel's own flow (stateless
    draft endpoint → review → create) and never lands in message metadata. It
    stays in the vocabulary so the surface that eventually stores one does not
    invent a sixth name — and this test says plainly that no slot produces it
    today, rather than leaving a reader to wonder whether it is broken.
    """
    assert "thesis_draft" in PROPOSAL_KINDS
    assert "thesis_draft" not in set(PROPOSAL_SLOTS.values())
    envelopes = await ProposalEnvelopeService(proposed).build(ROOM)
    assert not [e for e in envelopes if e.proposal_kind == "thesis_draft"]


@pytest.mark.asyncio
async def test_the_envelope_carries_context_before_action(proposed):
    """Spec 9.2: a proposal must show what changes, why, and what produced it."""
    envelopes = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    resolution = envelopes["prediction_resolution"]
    assert resolution.rationale == "settled above 90 all week"
    assert resolution.source_message_id == M_RESOLVE
    assert envelopes["thesis_proposal"].rationale == "the strait shuts"
    for e in envelopes.values():
        assert e.created_at is not None
        assert e.id.startswith("proposal:")


@pytest.mark.asyncio
async def test_stable_source_coordinates(proposed):
    envelopes = await ProposalEnvelopeService(proposed).build(ROOM)
    ids = [e.id for e in envelopes]
    assert len(ids) == len(set(ids))
    listed = _by_kind(envelopes)["commitment_proposal"]
    assert listed.id == f"proposal:{M_DRAFTS}:commitment_proposals[0]"


# ---------------------------------------------------------------------------
# D2 — the status lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_unacted_proposal_is_proposed_and_offers_the_action(proposed):
    envelopes = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    for kind in ("prediction_draft", "reading_draft", "commitment_proposal",
                 "prediction_resolution"):
        assert envelopes[kind].status == "proposed", kind
        assert "accept" in envelopes[kind].available_actions, kind


@pytest.mark.asyncio
async def test_a_past_deadline_expires_a_prediction_draft(proposed):
    """`expired` = the target is no longer actionable. A prediction whose
    deadline has passed cannot be logged; offering Accept would produce a
    tradingDesk refusal a human cannot act on."""
    # to_jsonb($2::text), not $2::jsonb: the connection carries the production
    # JSONB codec, which would json.dumps a Python string a SECOND time and
    # store a quoted-quoted date the parser then reads as malformed.
    await proposed.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata, '{proposal,deadline}',
                                    to_jsonb($2::text))
           WHERE id = $1""",
        M_DRAFTS, PAST)
    envelopes = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    assert envelopes["prediction_draft"].status == "expired"
    assert "accept" not in envelopes["prediction_draft"].available_actions
    assert "inspect" in envelopes["prediction_draft"].available_actions


@pytest.mark.asyncio
async def test_a_room_that_already_argues_a_thesis_expires_the_proposal(proposed):
    """One thesis per ordinary room (spec 12.2): once the room holds a book,
    an outstanding thesis proposal has nowhere to land."""
    before = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    assert before["thesis_proposal"].status == "proposed"

    await proposed.execute(
        "UPDATE rooms SET linked_book_id = 'strait-risk-graph' WHERE id = $1",
        ROOM)
    after = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    assert after["thesis_proposal"].status == "expired"
    assert after["thesis_proposal"].target_object == "thesis:strait-risk-graph"


@pytest.mark.asyncio
async def test_a_reading_filed_another_way_supersedes_the_draft(proposed):
    """SUPERSEDED, not failed — the two demand opposite responses.

    A draft whose article is already in the library did not fail: a newer
    attempt already has it. Reporting that as a failure sends a human to retry
    a write that has already happened.
    """
    await proposed.execute(
        """INSERT INTO reading_items (room_id,url,title,content,summary,source,
               created_at)
           VALUES ($1,$2,'Drafted reading','body','sum','wire',now())""",
        ROOM, DRAFT_URL)
    envelopes = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    reading = envelopes["reading_draft"]
    assert reading.status == "superseded"
    assert "accept" not in reading.available_actions
    assert reading.target_object.startswith("reading:")


@pytest.mark.asyncio
async def test_failed_is_in_the_vocabulary_though_no_row_records_it():
    """Spec 5.1 and 8.4: a human-authorized write that did not complete must
    stay visible.

    Nothing in the database can say `failed` today, and that is deliberate: on
    a relay failure the accepted flag stays FALSE precisely so a retry is a
    fresh accept rather than a conflict. So `failed` is a client-held state
    over this same envelope, and it is in the vocabulary because dropping it
    is how a failed write becomes an invisible one.
    """
    assert "failed" in PROPOSAL_STATUSES
    assert "dismissed" in PROPOSAL_STATUSES


# ---------------------------------------------------------------------------
# D3 — duplicate disarming, driven through the real relay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accepting_through_the_relay_disarms_the_envelope(proposed, monkeypatch):
    """The relay's own write, then the envelope, then the relay again.

    Nothing here stamps the flag by hand: that would only prove the envelope
    agrees with my copy of the relay's rule. The relay writes, the envelope
    must SEE it, and the second tap must be a conflict rather than a second
    prediction on the desk.
    """
    from fastapi import HTTPException

    import api.prediction_relay as relay
    from api.auth.dependencies import AuthenticatedUser

    posted = []

    async def fake_post(path, json_body=None):
        posted.append(json_body)
        return {"id": "pred-1", **(json_body or {})}

    monkeypatch.setattr(relay.td, "post", fake_post)
    token = await proposed.fetchval(
        "SELECT token FROM rooms WHERE id = $1", ROOM)
    caller = AuthenticatedUser(
        user_id=AMO, email="amo@test", email_verified=True, display_name="Amo")

    before = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    assert before["prediction_draft"].status == "proposed"
    assert "accept" in before["prediction_draft"].available_actions

    await relay.accept_prediction(
        room_id=ROOM,
        request=relay.AcceptPredictionRequest(message_id=M_DRAFTS),
        token=token, current_user=caller, db=proposed,
    )
    assert len(posted) == 1

    after = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    assert after["prediction_draft"].status == "accepted"
    assert "accept" not in after["prediction_draft"].available_actions
    # Spec 8.4: accepted proposals remain INSPECTABLE. They do not vanish.
    assert "inspect" in after["prediction_draft"].available_actions
    assert after["prediction_draft"].payload["statement"] == "Brent over 90"

    with pytest.raises(HTTPException) as second:
        await relay.accept_prediction(
            room_id=ROOM,
            request=relay.AcceptPredictionRequest(message_id=M_DRAFTS),
            token=token, current_user=caller, db=proposed,
        )
    assert second.value.status_code == 409
    assert len(posted) == 1, "a second tap reached tradingDesk"


@pytest.mark.asyncio
async def test_acceptance_preserves_the_accepting_human_where_it_is_recorded(proposed):
    """Spec 9.3 asks acceptance to preserve the accepting human. Two kinds
    record it; two do not, and the envelope must say null rather than guess.

    reading_draft and commitment_proposal both write a row carrying the actor
    and a timestamp, joined here on the real source_message_id FK. The two
    tradingDesk-crossing kinds write only a boolean — see the ledger.
    """
    await proposed.execute(
        """INSERT INTO reading_items (room_id,url,title,content,summary,source,
               source_message_id,saved_by_user_id,created_at)
           VALUES ($1,$2,'Drafted reading','body','sum','proposal',$3,$4,now())""",
        ROOM, DRAFT_URL, M_DRAFTS, AMO)
    await proposed.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata, '{reading_proposal,accepted}',
                                    'true'::jsonb)
           WHERE id = $1""", M_DRAFTS)
    await proposed.execute(
        """INSERT INTO commitments (id,room_id,thread_id,source_message_id,claim,
               resolution_criteria,category,status,created_by_user_id,created_at)
           VALUES ($1,$2,$3,$4,'I close before CPI','flat','commitment','active',
                   $5,now())""",
        _uid(0xD51), ROOM, TH, M_DRAFTS, AMO)
    await proposed.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata,
                   '{commitment_proposals,0,accepted}', 'true'::jsonb)
           WHERE id = $1""", M_DRAFTS)

    envelopes = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))
    for kind in ("reading_draft", "commitment_proposal"):
        assert envelopes[kind].status == "accepted", kind
        assert envelopes[kind].accepted_by == AMO, kind
        assert envelopes[kind].accepted_at is not None, kind
    assert envelopes["reading_draft"].target_object.startswith("reading:")
    assert envelopes["commitment_proposal"].target_object == \
        f"commitment:{_uid(0xD51)}"
    # No row anywhere records who logged a prediction — null, never a guess.
    assert envelopes["prediction_draft"].accepted_by is None


# ---------------------------------------------------------------------------
# The accepting human — spec 9.3, approved by the owner 2026-08-13
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accepting_a_prediction_records_who_did_it(proposed, monkeypatch):
    """Spec 9.3: acceptance must preserve the accepting human.

    Release 1 shipped this as null for the two tradingDesk-crossing kinds,
    because the relay wrote only a boolean and logged no event — there was
    nowhere to read an actor from. The owner approved the write; this is the
    guard that it happens, driven through the REAL relay rather than a
    hand-stamped flag.
    """
    import api.prediction_relay as relay
    from api.auth.dependencies import AuthenticatedUser

    monkeypatch.setattr(relay.td, "post", lambda *a, **k: _ok({"id": "p"}))
    token = await proposed.fetchval("SELECT token FROM rooms WHERE id = $1", ROOM)
    caller = AuthenticatedUser(
        user_id=AMO, email="amo@test", email_verified=True, display_name="Amo")

    await relay.accept_prediction(
        room_id=ROOM,
        request=relay.AcceptPredictionRequest(message_id=M_DRAFTS),
        token=token, current_user=caller, db=proposed,
    )

    envelope = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))["prediction_draft"]
    assert envelope.status == "accepted"
    assert envelope.accepted_by == AMO
    assert envelope.accepted_at is not None
    # And the payload it was accepted FROM is untouched — the stamp records
    # the decision beside the proposal, it does not rewrite it.
    assert envelope.payload["statement"] == "Brent over 90"


@pytest.mark.asyncio
async def test_accepting_a_resolution_records_who_did_it(proposed, monkeypatch):
    import api.prediction_relay as relay
    from api.auth.dependencies import AuthenticatedUser

    monkeypatch.setattr(relay.td, "post", lambda *a, **k: _ok({"resolved": True}))
    token = await proposed.fetchval("SELECT token FROM rooms WHERE id = $1", ROOM)
    caller = AuthenticatedUser(
        user_id=AMO, email="amo@test", email_verified=True, display_name="Amo")

    await relay.resolve_accept(
        room_id=ROOM, prediction_id="p1",
        request=relay.ResolveAcceptRequest(verdict="correct"),
        token=token, current_user=caller, db=proposed,
    )

    envelope = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))["prediction_resolution"]
    assert envelope.status == "accepted"
    assert envelope.accepted_by == AMO
    assert envelope.accepted_at is not None


@pytest.mark.asyncio
async def test_a_proposal_accepted_before_the_stamp_still_names_its_human(proposed):
    """Backward compatibility, which is the whole reason the row join stays.

    Every proposal accepted before this change carries a bare `accepted: true`
    and no actor. Those must not regress to "nobody accepted this" — for the
    two kinds whose acceptance writes a row, the human is still there to be
    found, and the envelope must still find them.
    """
    await proposed.execute(
        """INSERT INTO reading_items (room_id,url,title,content,summary,source,
               source_message_id,saved_by_user_id,created_at)
           VALUES ($1,$2,'Drafted reading','body','sum','proposal',$3,$4,now())""",
        ROOM, DRAFT_URL, M_DRAFTS, AMO)
    # The OLD shape: the flag alone, exactly as the relay used to write it.
    await proposed.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata, '{reading_proposal,accepted}',
                                    'true'::jsonb)
           WHERE id = $1""", M_DRAFTS)

    envelope = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))["reading_draft"]
    assert envelope.status == "accepted"
    assert envelope.accepted_by == AMO, "the legacy row join stopped working"


@pytest.mark.asyncio
async def test_the_stamp_is_what_the_envelope_trusts(proposed):
    """When both exist, the stamp wins — it records who pressed the button,
    while the row records who the write was attributed to. They are the same
    person today, and the stamp is the one that says so directly."""
    other = _uid(0xD02)
    await proposed.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,now(),'Dan')",
        other)
    await proposed.execute(
        """INSERT INTO reading_items (room_id,url,title,content,summary,source,
               source_message_id,saved_by_user_id,created_at)
           VALUES ($1,$2,'Drafted reading','body','sum','proposal',$3,$4,now())""",
        ROOM, DRAFT_URL, M_DRAFTS, other)
    await proposed.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata, '{reading_proposal}',
                   metadata->'reading_proposal' || $2::jsonb)
           WHERE id = $1""",
        # A dict, not json.dumps: the connection carries the production JSONB
        # codec, and a Python string would be encoded a SECOND time — the
        # payload then merges as an ARRAY and the slot stops being a proposal.
        M_DRAFTS,
        {"accepted": True, "accepted_by": str(AMO),
         "accepted_at": "2026-08-13T05:00:00+00:00"})

    envelope = _by_kind(await ProposalEnvelopeService(proposed).build(ROOM))["reading_draft"]
    assert envelope.accepted_by == AMO


# ---------------------------------------------------------------------------
# D4 — migration safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_claim_check_is_not_a_proposal(proposed):
    """A claim check is a nudge, not a decision. It must not acquire an Accept
    button by passing through a normalizer that assumed every metadata badge is
    a proposal."""
    envelopes = await ProposalEnvelopeService(proposed).build(ROOM)
    assert not [e for e in envelopes if e.source_message_id == M_CLAIM]
    untouched = await proposed.fetchval(
        "SELECT metadata->'claim_check'->>'verdict' FROM messages WHERE id = $1",
        M_CLAIM)
    assert untouched == "mixed"


@pytest.mark.asyncio
async def test_the_envelope_writes_nothing(proposed):
    """It reads state and routes a human's action to the relay that already
    exists. A normalizer that writes is a second write path."""
    tables = ("messages", "reading_items", "commitments", "rooms", "memories",
              "events")
    before = {t: await proposed.fetchval(f"SELECT count(*) FROM {t}")
              for t in tables}
    metadata_before = await proposed.fetchval(
        "SELECT metadata::text FROM messages WHERE id = $1", M_DRAFTS)

    await ProposalEnvelopeService(proposed).build(ROOM)

    after = {t: await proposed.fetchval(f"SELECT count(*) FROM {t}")
             for t in tables}
    assert before == after
    assert metadata_before == await proposed.fetchval(
        "SELECT metadata::text FROM messages WHERE id = $1", M_DRAFTS)


@pytest.mark.asyncio
async def test_envelopes_are_fenced_to_their_room(proposed):
    envelopes = await ProposalEnvelopeService(proposed).build(ROOM)
    assert envelopes
    assert all(e.room_id == ROOM for e in envelopes)
    blob = "\n".join(e.model_dump_json() for e in envelopes)
    assert "OTHER-ROOM-SENTINEL" not in blob


# ---------------------------------------------------------------------------
# One definition of a proposal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_workspace_proposal_objects_come_from_the_envelope(proposed):
    """C's Proposal objects and D's envelopes must not be two answers to
    'what is a proposal'. The adapter projects the envelope; it does not
    re-read the metadata."""
    from workspace_objects import WorkspaceObjectService

    envelopes = await ProposalEnvelopeService(proposed).build(ROOM)
    objects = await WorkspaceObjectService(proposed).proposals(ROOM)
    assert {o.id for o in objects} == {e.id for e in envelopes}
    by_id = {e.id: e for e in envelopes}
    for o in objects:
        assert o.provenance.detail == by_id[o.id].proposal_kind
        assert o.kind == "proposal"


def test_the_proposal_actions_are_a_subset_of_the_workspace_actions():
    """Two vocabularies for the same buttons is how they drift apart."""
    from workspace_objects import WORKSPACE_ACTIONS

    assert set(PROPOSAL_ACTIONS) <= set(WORKSPACE_ACTIONS)
