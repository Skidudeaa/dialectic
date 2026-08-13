# proposal_envelope.py — one contract for every proposal the room can accept.
#
# ARCHITECTURE: a NORMALIZER over storage that already exists (design v2
# §8.3–8.4). Five different proposal shapes live in `messages.metadata` today,
# each with its own card and its own relay. This module gives them one shape so
# a surface teaches the trust rule once — "Dialectic can prepare the move, a
# human makes it real" (§9.1) — instead of teaching five unrelated exceptions.
#
# WHAT THIS IS NOT: a write path. Release 1 changes no stored proposal contract
# and touches no relay endpoint. The envelope READS state and names the action a
# surface may route to the relay that already owns the write. A normalizer that
# writes would be a second door onto entities that already have one, and the
# idempotency each relay implements would then have two places to be right.
#
# ONE DEFINITION OF A PROPOSAL: workspace_objects.py projects its Proposal
# objects FROM these envelopes rather than re-reading the metadata, so C and D
# cannot answer "what is a proposal" differently.
#
# WHAT THE STORAGE CANNOT SAY, recorded here because the gap is invisible from
# the contract alone:
#   - `failed` has no row. On a relay failure the accepted flag deliberately
#     stays FALSE, so a retry is a fresh accept rather than a conflict — which
#     means failure is a CLIENT-held state over this envelope. It stays in the
#     vocabulary because dropping it is how a failed write becomes a silent one
#     (§5.1, §9.3).
#   - `dismissed` has no row either: nothing in the shipped UI dismisses a
#     proposal.
#   - `accepted_by` / `accepted_at` are derivable for exactly two kinds. A
#     reading and a commitment each write a row carrying the actor, joined here
#     on a real source_message_id FK. The two tradingDesk-crossing kinds write
#     only a boolean and log no event, so their accepting human is not
#     preserved anywhere — §9.3 asks for it and today's storage cannot give it.
#     Null, never a guess.

import json
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

# The normalized kinds of §8.3. `thesis_draft` is named but stored nowhere: a
# thesis draft lives inside the Create Thesis panel's own flow (draft endpoint →
# human review → create) and never lands in message metadata. It stays in the
# vocabulary so whatever eventually stores one does not invent a sixth name.
PROPOSAL_KINDS = (
    "prediction_draft",
    "thesis_proposal",
    "thesis_draft",
    "commitment_proposal",
    "reading_draft",
    "prediction_resolution",
)

# The visible lifecycle of §8.4. The spec writes the third state as "rejected or
# dismissed"; it is ONE state and carries one name here, because two names for
# one state is how a surface ends up rendering both.
PROPOSAL_STATUSES = (
    "proposed",
    "accepted",
    "dismissed",
    "superseded",
    "expired",
    "failed",
)

# A subset of workspace_objects.WORKSPACE_ACTIONS — asserted as a subset by a
# test, so the buttons cannot drift into two vocabularies.
PROPOSAL_ACTIONS = ("accept", "dismiss", "inspect", "open_thesis")

# metadata slot → normalized kind. The single mapping; the workspace adapter
# and the frontend both read this table rather than keeping their own.
PROPOSAL_SLOTS = {
    "proposal": "prediction_draft",
    "thesis_proposal": "thesis_proposal",
    "reading_proposal": "reading_draft",
    "resolution_proposal": "prediction_resolution",
}
# One slot holds a LIST — the commitment detector may hoist up to three.
PROPOSAL_LIST_SLOT = "commitment_proposals"
PROPOSAL_LIST_KIND = "commitment_proposal"

# Bounded like every other projection: messages carrying proposals, newest
# first. One message can yield several envelopes, so this caps carriers rather
# than envelopes — a cap on envelopes would truncate a single message's
# proposals mid-card.
PROPOSAL_CARRIER_CAP = 50

# Every message in the room carrying any proposal slot. Fenced on room_id.
# Imported by workspace_objects so there is one statement, not two.
PROPOSALS_SQL = """
SELECT m.id, m.thread_id, m.created_at, m.edited_at, m.metadata,
       m.speaker_type, m.user_id
FROM messages m JOIN threads t ON t.id = m.thread_id
WHERE t.room_id = $1 AND NOT m.is_deleted
  AND (m.metadata ? 'proposal'
       OR m.metadata ? 'thesis_proposal'
       OR m.metadata ? 'reading_proposal'
       OR m.metadata ? 'resolution_proposal'
       OR m.metadata ? 'commitment_proposals')
ORDER BY m.created_at DESC
LIMIT $2
"""

# The room state a status derives from. One read, not one per envelope.
_ROOM_SQL = "SELECT linked_book_id FROM rooms WHERE id = $1"

# Readings the room already holds, keyed by url. A draft whose article is
# already filed is SUPERSEDED, not failed — the two demand opposite responses
# from a human, and conflating them sends someone to retry a write that has
# already happened.
_FILED_READINGS_SQL = """
SELECT id, url, saved_by_user_id, created_at, source_message_id
FROM reading_items
WHERE room_id = $1
"""

# Commitments created FROM a proposal card, joined on the real FK the accept
# path writes (transport/handlers._handle_create_commitment passes it through).
_ACCEPTED_COMMITMENTS_SQL = """
SELECT id, claim, created_by_user_id, created_at, source_message_id
FROM commitments
WHERE room_id = $1 AND source_message_id = ANY($2::uuid[])
"""


def acceptance_stamp(user_id: UUID, at: Optional[datetime] = None) -> dict:
    """What a human's acceptance records, in one place.

    Spec §9.3 asks acceptance to preserve the accepting human. It is written
    beside the proposal, in the same patch that sets `accepted`, because the
    two facts are one event: a second write (or a second table) could be
    interrupted between them and leave a proposal accepted by nobody.

    Four relays call this, so what an acceptance MEANS has one definition
    rather than four that drift. The payload keys mirror the envelope fields
    exactly, so no translation layer sits between the write and the read.
    """
    return {
        "accepted": True,
        "accepted_by": str(user_id),
        "accepted_at": (at or datetime.now(timezone.utc)).isoformat(),
    }


# Merge the stamp INTO the proposal slot rather than setting one key: the rest
# of the payload is what the human accepted and must survive untouched.
ACCEPT_SLOT_SQL = """
UPDATE messages
SET metadata = jsonb_set(metadata, ARRAY[$2::text],
                         COALESCE(metadata->$2::text, '{}'::jsonb) || $3::jsonb)
WHERE id = $1
"""

# The list slot needs the index in the path AND in the read.
ACCEPT_LIST_ITEM_SQL = """
UPDATE messages
SET metadata = jsonb_set(
        metadata,
        ARRAY['commitment_proposals', $2::text],
        COALESCE(metadata->'commitment_proposals'->$3::int, '{}'::jsonb) || $4::jsonb)
WHERE id = $1
  AND metadata->'commitment_proposals'->$3::int IS NOT NULL
"""


class ProposalEnvelope(BaseModel):
    """One proposal, whatever shape it is stored in.

    `id` is a stable SOURCE COORDINATE, not a row id: these live in message
    metadata, and the message plus the slot is the only address they have.
    """
    id: str
    proposal_kind: str
    source_message_id: UUID
    room_id: UUID
    branch_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    rationale: str
    payload: dict = {}
    status: str
    accepted_by: Optional[UUID] = None
    accepted_at: Optional[datetime] = None
    target_object: Optional[str] = None
    available_actions: list[str] = []


class ProposalEnvelopeProjection(BaseModel):
    generated_at: datetime
    room_id: UUID
    proposals: list[ProposalEnvelope]


def _jsonb(value: Any) -> dict:
    """A JSONB column as a dict, whichever way the connection hands it over.

    Same reasoning as workspace_objects._jsonb: production reads arrive decoded
    through the pool's codec, a bare connection hands back text, and silently
    treating text as empty would render a room with no proposals at all.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _uuid_or_none(value: Any) -> Optional[UUID]:
    """A stamped id, or nothing. Metadata is a document, not a trust boundary:
    a malformed value means the actor is unknown, never an exception on read."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _rationale(kind: str, payload: dict) -> str:
    """Why Dialectic proposed it (§9.2), from what the payload actually has."""
    for key in ("rationale", "claim", "resolution_criteria", "summary",
                "statement", "title"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:300]
    return ""


def _deadline_passed(payload: dict) -> bool:
    raw = str(payload.get("deadline") or "").strip()
    if not raw:
        return False
    try:
        return date.fromisoformat(raw) < datetime.now(timezone.utc).date()
    except ValueError:
        # A malformed deadline is the relay's 422, not an expiry. Leave the
        # proposal actionable and let the write path say why it refused.
        return False


def _actions(status: str, kind: str) -> list[str]:
    """What a surface MAY offer. Naming an action performs nothing.

    Accepted proposals keep `inspect` because §8.4 requires them to remain
    inspectable — an accepted proposal does not vanish as if it never happened.
    """
    if status != "proposed":
        return ["inspect"]
    if kind == "thesis_proposal":
        # No direct write: the tap opens the Create Thesis panel, where the
        # cascade is drafted and reviewed before anything is created.
        return ["open_thesis", "dismiss", "inspect"]
    return ["accept", "dismiss", "inspect"]


class ProposalEnvelopeService:
    """Normalizes one room's stored proposals. Reads only."""

    def __init__(self, db):
        self.db = db

    async def build(self, room_id: UUID) -> list[ProposalEnvelope]:
        rows = await self.db.fetch(PROPOSALS_SQL, room_id, PROPOSAL_CARRIER_CAP)
        if not rows:
            return []
        message_ids = [row["id"] for row in rows]

        room = await self.db.fetchrow(_ROOM_SQL, room_id)
        book = room["linked_book_id"] if room else None
        filed = await self.db.fetch(_FILED_READINGS_SQL, room_id)
        by_url = {row["url"]: row for row in filed}
        commitments = await self.db.fetch(
            _ACCEPTED_COMMITMENTS_SQL, room_id, message_ids,
        )
        commitment_by = {
            (row["source_message_id"], row["claim"]): row for row in commitments
        }

        envelopes: list[ProposalEnvelope] = []
        for row in rows:
            metadata = _jsonb(row["metadata"])
            for field, kind, payload in proposal_slots(metadata):
                envelopes.append(self._envelope(
                    row, room_id, field, kind, payload,
                    book=book, by_url=by_url, commitment_by=commitment_by,
                ))
        return envelopes

    def _envelope(self, row, room_id, field, kind, payload, *,
                  book, by_url, commitment_by) -> ProposalEnvelope:
        accepted = bool(payload.get("accepted"))
        # The stamp the accept path writes (acceptance_stamp). It is the
        # DIRECT record of who pressed the button; the row joins below stay
        # as the fallback for everything accepted before the stamp existed,
        # which would otherwise regress to "nobody accepted this".
        accepted_by = _uuid_or_none(payload.get("accepted_by"))
        accepted_at = _datetime_or_none(payload.get("accepted_at"))
        target: Optional[str] = None
        status = "accepted" if accepted else "proposed"

        if kind == "reading_draft":
            filed = by_url.get(str(payload.get("url") or ""))
            if filed is not None:
                target = f"reading:{filed['id']}"
                if accepted and accepted_by is None:
                    # Pre-stamp fallback: the relay files the reading and
                    # stamps the flag in the same request, so this row is the
                    # only acceptance record older proposals have.
                    accepted_by = filed["saved_by_user_id"]
                    accepted_at = filed["created_at"]
                elif status == "proposed":
                    status = "superseded"

        elif kind == "commitment_proposal":
            made = commitment_by.get((row["id"], str(payload.get("claim") or "")))
            if made is not None:
                target = f"commitment:{made['id']}"
                if accepted and accepted_by is None:
                    # Pre-stamp fallback, as above.
                    accepted_by = made["created_by_user_id"]
                    accepted_at = made["created_at"]

        elif kind == "thesis_proposal":
            if book:
                target = f"thesis:{book}"
                if not accepted:
                    # One thesis per ordinary room (§12.2): the room already
                    # argues one, so this proposal has nowhere to land. NOT
                    # attributed to a human — THESIS_CREATED is room-level and
                    # naming this proposal as its cause would be a guess.
                    status = "expired"

        elif kind == "prediction_draft":
            if not accepted and _deadline_passed(payload):
                status = "expired"

        return ProposalEnvelope(
            id=f"proposal:{row['id']}:{field}",
            proposal_kind=kind,
            source_message_id=row["id"],
            room_id=room_id,
            branch_id=row["thread_id"],
            created_by=row["user_id"],
            created_at=row["created_at"],
            rationale=_rationale(kind, payload),
            payload=payload,
            status=status,
            accepted_by=accepted_by,
            accepted_at=accepted_at,
            target_object=target,
            available_actions=_actions(status, kind),
        )


def proposal_slots(metadata: dict) -> list[tuple[str, str, dict]]:
    """Every proposal a message carries, as (coordinate, kind, payload).

    Deliberately narrow: a metadata key that is not in PROPOSAL_SLOTS is not a
    proposal. `claim_check` is the case that matters — it is a nudge, not a
    decision, and a normalizer that assumed every badge is a proposal would
    hand it an Accept button it must never have.
    """
    slots: list[tuple[str, str, dict]] = []
    for slot, kind in PROPOSAL_SLOTS.items():
        payload = metadata.get(slot)
        if isinstance(payload, dict):
            slots.append((slot, kind, payload))
    listed = metadata.get(PROPOSAL_LIST_SLOT)
    if isinstance(listed, list):
        for index, payload in enumerate(listed):
            if isinstance(payload, dict):
                slots.append((
                    f"{PROPOSAL_LIST_SLOT}[{index}]", PROPOSAL_LIST_KIND, payload,
                ))
    return slots


async def build_proposal_projection(db, room_id: UUID) -> ProposalEnvelopeProjection:
    return ProposalEnvelopeProjection(
        generated_at=datetime.now(timezone.utc),
        room_id=room_id,
        proposals=await ProposalEnvelopeService(db).build(room_id),
    )
