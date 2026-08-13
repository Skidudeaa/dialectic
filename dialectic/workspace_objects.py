# workspace_objects.py — one shape for everything a workroom holds.
#
# ARCHITECTURE: ADAPTERS, NOT A TABLE (design v2 §8.1, §19.4). Every entity
# projected here already has its own storage, its own write path and its own
# lifecycle. A WorkspaceObject is a READ-ONLY projection of one of those rows
# into a single shape the surfaces can render without learning eight schemas.
# Nothing in this module writes, and no entity changes lifecycle because it was
# projected — `available_actions` says what a surface MAY offer, and performs
# nothing (§C4).
#
# THE TWIN RULE — the highest-risk invariant in this file.
# llm/reading.py deliberately writes a reading AND a memory twin keyed
# `reading:<domain>-<slug>` with dedup=False, so three-lane recall finds
# readings unchanged. They are two real, independent rows describing ONE thing,
# and they project to ONE object carrying BOTH source_entity references. Two
# guards, because either alone can be masked by the other:
#   1. the reading adapter absorbs its twin, paired through
#      llm.reading._reading_key — the writer's own function, never a second
#      copy of the key rule;
#   2. the dossier adapter excludes the entire `reading:` key namespace in SQL,
#      so a twin whose reading was later re-titled cannot resurface as a
#      second, differently-worded Dossier entry.
# Observed on production 2026-08-12: 13 readings, 13 twins, 13 paired by key,
# 0 orphans. A naive adapter emits 26 objects and looks entirely correct in a
# screenshot, because each pair renders as two plausible entries. Only a count
# assertion catches it.
#
# THE SECOND TWIN, found while building this file: api/trading_ingest.py
# upserts a `thesis_state_current` memory that shadows rooms.trading_config.
# Same shape, same rule — the thesis adapter absorbs the slot and the dossier
# excludes it.
#
# WHAT IS NOT A TWIN, so a later reader does not "fix" it: one message can
# project as a Record event AND a Research Brief AND several Proposals. That is
# one row in several ROLES, not several rows describing one thing — the Record
# is the transcript and must contain the message (§6.4, §5.8), while the Bench
# renders the proposals it carries. Collapsing those would delete the Record's
# copy of a message because a higher-order artifact summarized it, which §6.4
# forbids in as many words.

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from api.trading_ingest import THESIS_STATE_MEMORY_KEY
from home_activity import COMMITMENT_DUE_WINDOW, HomeActivityMovement
from llm.reading import _reading_key
from proposal_envelope import ProposalEnvelopeService, proposal_slots

# The kinds the adapter set produces (§8.1's adapter list). Closed vocabulary:
# a surface switches on these, so an unlisted value is a bug, not an extension.
WORKSPACE_OBJECT_KINDS = (
    "reading",
    "research_brief",
    "thesis",
    "commitment",
    "proposal",
    "dossier_entry",
    "house_movement",
    "record_event",
)

# Who or what produced the underlying row. `detail` carries the specific source
# string (a reading's source, a proposal kind, an event type) — origin stays a
# closed set so a surface can style attribution without a lookup table.
WORKSPACE_ORIGINS = ("human", "dialectic", "desk", "system")

# The judgment axis, deliberately distinct from `status`. `status` is the
# entity's OWN lifecycle; review_state is what a human still owes. `failed` is
# unreachable from these read-only adapters and exists because Task Group D's
# envelope reuses this vocabulary — a human-authorized write that did not
# complete must stay visible (§5.1, §8.4), never silently absent.
WORKSPACE_REVIEW_STATES = (
    "none", "awaiting_human", "accepted", "dismissed", "resolved", "failed",
)

# What a surface MAY offer for this object. Descriptive only — see §C4.
WORKSPACE_ACTIONS = (
    "open_room", "open_branch", "open_message", "open_source", "open_thesis",
    "accept", "dismiss", "resolve", "inspect",
)

# How a proposal's own lifecycle reads on the workspace object's review axis.
# `failed` is a client-held state (see proposal_envelope) and cannot arrive
# from a read, but it is mapped here so it can never fall through to "none" --
# a failed write that renders as nothing to answer is the defect the status
# exists to expose.
_REVIEW_FOR_PROPOSAL_STATUS = {
    "proposed": "awaiting_human",
    "accepted": "accepted",
    "dismissed": "dismissed",
    "superseded": "none",
    "expired": "none",
    "failed": "failed",
}

# Per-kind bounds, applied inside each adapter's OWN statement.
#
# WHY per kind rather than one global newest-N: Task Group B shipped a single
# global `ORDER BY … LIMIT` and a room with 250 recent readings consumed the
# whole budget, projecting every other room to zero while the House still
# looked healthy. The same failure here is one prolific kind evicting every
# other kind from a workroom. Ranking is per kind because each adapter is its
# own statement — no kind can spend another kind's budget.
_PER_KIND_CAP = 50
# The Record is the transcript: it is meant to be long, and it is the one kind
# whose value IS its density. Bounded separately so it can be generous without
# raising the ceiling for kinds where 50 is already more than a surface shows.
#
# Applied PER SOURCE — speech and operations each get this many — for the same
# reason the caps are per kind at all. A room whose event log is chattier than
# its conversation would otherwise evict the transcript from its own Record,
# which is the starvation bug wearing a different hat.
_RECORD_CAP = 100



class WorkspaceSourceRef(BaseModel):
    """Exactly where this projection came from.

    `field` is what makes a coordinate stable for rows that carry several
    objects — a message holding four proposals yields four refs to the same
    id, distinguished by the metadata slot. Task Group D's envelope needs the
    coordinate, not a re-parse of the object's id string.
    """
    entity: str
    id: str
    field: Optional[str] = None


class WorkspaceRelationship(BaseModel):
    relation: str
    entity: str
    id: str


class WorkspaceProvenance(BaseModel):
    origin: str
    actor_user_id: Optional[UUID] = None
    detail: Optional[str] = None


class WorkspaceObject(BaseModel):
    """One thing a workroom holds, in the shape every surface can render.

    A PROJECTION, never a copy: `source_entity` names the rows that own the
    truth, and every field here is derived from them at read time.
    """
    id: str
    kind: str
    room_id: UUID
    branch_id: Optional[UUID] = None
    title: str
    summary: str
    status: str
    created_at: datetime
    updated_at: datetime
    provenance: WorkspaceProvenance
    relationships: list[WorkspaceRelationship] = []
    available_actions: list[str] = []
    review_state: str
    source_entity: list[WorkspaceSourceRef] = []
    source_event: Optional[WorkspaceSourceRef] = None


# --- adapter statements ----------------------------------------------------
#
# Every statement is fenced on room_id. A workroom projection may never reach
# a room the caller did not ask for, in any kind, at any depth.

_READINGS_SQL = """
SELECT ri.id, ri.url, ri.title, ri.site, ri.summary, ri.source,
       ri.source_message_id, ri.saved_by_user_id, ri.created_at,
       m.thread_id AS branch_id
FROM reading_items ri
LEFT JOIN messages m ON m.id = ri.source_message_id
WHERE ri.room_id = $1
ORDER BY ri.created_at DESC
LIMIT $2
"""

# Twins are fetched BY KEY rather than by a capped scan: pairing must not
# depend on two ORDER BYs agreeing, or a reading inside the cap could lose a
# twin that fell outside it and split into two objects.
_READING_TWINS_SQL = """
SELECT id, key, created_at, updated_at
FROM memories
WHERE room_id = $1 AND status = 'active' AND key = ANY($2::text[])
"""

_BRIEFS_SQL = """
SELECT m.id, m.thread_id, m.content, m.created_at, m.edited_at, m.metadata,
       m.speaker_type, m.user_id
FROM messages m JOIN threads t ON t.id = m.thread_id
WHERE t.room_id = $1 AND NOT m.is_deleted
  AND m.metadata->>'source' = 'deep_dive'
ORDER BY m.created_at DESC
LIMIT $2
"""

_THESIS_SQL = f"""
SELECT r.id, r.name, r.linked_book_id, r.trading_config,
       r.last_trading_push_at, r.created_at, r.is_home,
       mem.id AS memory_id, mem.updated_at AS memory_updated_at,
       ev.id AS event_id, ev.event_type, ev.thread_id AS event_thread_id
FROM rooms r
LEFT JOIN LATERAL (
    SELECT id, updated_at FROM memories
    WHERE room_id = r.id AND key = '{THESIS_STATE_MEMORY_KEY}'
      AND status = 'active'
    ORDER BY created_at DESC LIMIT 1
) mem ON true
LEFT JOIN LATERAL (
    SELECT id, event_type, thread_id FROM events
    WHERE room_id = r.id AND event_type = 'THESIS_CREATED'
    ORDER BY timestamp DESC LIMIT 1
) ev ON true
WHERE r.id = $1 AND r.linked_book_id IS NOT NULL
"""

_COMMITMENTS_SQL = f"""
SELECT id, thread_id, claim, resolution_criteria, category, status,
       deadline, resolution, created_at, created_by_user_id, resolved_at,
       source_message_id,
       (status = 'active' AND deadline IS NOT NULL
        AND deadline <= NOW() + INTERVAL '{COMMITMENT_DUE_WINDOW}') AS is_due
FROM commitments
WHERE room_id = $1
ORDER BY COALESCE(deadline, created_at) DESC
LIMIT $2
"""

# The `reading:` exclusion is one half of the twin rule and is asserted
# directly against this statement — see the B lesson: a guard the pipeline can
# shadow must be tested where it lives, not through the service.
#
# The owner fence is belt to the braces: room memories carry NULL
# owner_user_id today (observed production 2026-08-12: 436 rows, 0 owned), but
# the column exists and MemoryManager accepts it, and a personal memory
# surfacing in a shared workroom would breach §5.4.
_DOSSIER_SQL = f"""
SELECT id, key, content, scope, status, created_at, updated_at,
       created_by_user_id, speaker_user_id, source_message_id,
       (SELECT thread_id FROM messages WHERE id = memories.source_message_id)
           AS branch_id
FROM memories
WHERE room_id = $1
  AND status = 'active'
  AND key NOT LIKE 'reading:%'
  AND key <> '{THESIS_STATE_MEMORY_KEY}'
  AND (owner_user_id IS NULL OR owner_user_id = $2)
ORDER BY updated_at DESC
LIMIT $3
"""

# The Record is speech AND operations (§6.4): the transcript rows and the
# event-sourced log that surrounds them, in one chronological read.
_RECORD_SQL = """
(
    SELECT 'message' AS source, m.id, m.thread_id, m.created_at AS occurred_at,
           m.message_type AS label, left(m.content, 200) AS body,
           m.speaker_type, m.user_id, m.edited_at
    FROM messages m JOIN threads t ON t.id = m.thread_id
    WHERE t.room_id = $1 AND NOT m.is_deleted
    ORDER BY m.created_at DESC
    LIMIT $2
)
UNION ALL
(
    SELECT 'event', e.id, e.thread_id, e.timestamp,
           e.event_type, left(e.payload::text, 200),
           NULL::text, e.user_id, NULL::timestamptz
    FROM events e
    WHERE e.room_id = $1
    ORDER BY e.timestamp DESC
    LIMIT $2
)
ORDER BY occurred_at DESC
"""


def _jsonb(value: Any) -> dict:
    """A JSONB column as a dict, whichever way the connection hands it over.

    Production reads run through the pool's JSONB codec (api/main.py) and
    arrive already decoded. A connection without that codec — a one-off script,
    a bare asyncpg connect — hands back text. Decoding here rather than
    assuming keeps a mis-wired connection from silently projecting an object
    with no title, no phase and no proposals, which reads exactly like an empty
    room.
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


def _clip(text: Optional[str], limit: int = 120) -> str:
    """First meaningful line, bounded. Titles are labels, not paragraphs."""
    for line in str(text or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:limit]
    return ""


def _origin_for_speaker(speaker_type: Optional[str]) -> str:
    return "human" if speaker_type == "human" else "dialectic"


def _as_uuid(value: Any) -> Optional[UUID]:
    return value if isinstance(value, UUID) else None


class WorkspaceObjectService:
    """Projects one room's entities into the workspace-object shape.

    Read-only by construction: every statement above is a SELECT, and the
    service holds no write path at all.
    """

    def __init__(self, db):
        self.db = db

    async def build(
        self, room_id: UUID, viewer_user_id: Optional[UUID] = None,
    ) -> list[WorkspaceObject]:
        """Every projectable object in the room, newest first.

        House movement is deliberately absent: it is a CROSS-room Home
        projection that home_activity.py already builds and fences by Home
        membership. Reforking that fence here is exactly the mistake C2 warns
        against — use `workspace_object_from_movement` on what the House
        already returned.
        """
        objects: list[WorkspaceObject] = []
        objects += await self.readings(room_id)
        objects += await self.research_briefs(room_id)
        objects += await self.theses(room_id)
        objects += await self.commitments(room_id)
        objects += await self.proposals(room_id)
        objects += await self.dossier(room_id, viewer_user_id)
        objects += await self.record_events(room_id)
        objects.sort(key=lambda o: (o.updated_at, o.id), reverse=True)
        return objects

    # --- C2 adapters -------------------------------------------------------

    async def readings(self, room_id: UUID) -> list[WorkspaceObject]:
        """reading_items → Reading, with its memory twin folded in."""
        rows = await self.db.fetch(_READINGS_SQL, room_id, _PER_KIND_CAP)
        if not rows:
            return []

        # The key is computed by the WRITER's own function, so the pairing can
        # never drift from the rule that produced the twin.
        keys = {
            row["id"]: _reading_key({"url": row["url"], "title": row["title"]})
            for row in rows
        }
        twin_rows = await self.db.fetch(
            _READING_TWINS_SQL, room_id, list(set(keys.values())),
        )
        twins = {row["key"]: row for row in twin_rows}

        objects = []
        for row in rows:
            twin = twins.get(keys[row["id"]])
            sources = [WorkspaceSourceRef(
                entity="reading_items", id=str(row["id"]),
            )]
            if twin is not None:
                sources.append(WorkspaceSourceRef(
                    entity="memories", id=str(twin["id"]), field="twin",
                ))
            relationships = []
            if row["source_message_id"] is not None:
                relationships.append(WorkspaceRelationship(
                    relation="source_message", entity="messages",
                    id=str(row["source_message_id"]),
                ))
            actions = ["open_source", "open_room"]
            if row["branch_id"] is not None:
                actions.append("open_branch")
            updated = row["created_at"]
            if twin is not None and twin["updated_at"] is not None:
                updated = max(updated, twin["updated_at"])
            objects.append(WorkspaceObject(
                id=f"reading:{row['id']}",
                kind="reading",
                room_id=room_id,
                branch_id=row["branch_id"],
                title=row["title"] or row["url"],
                summary=row["summary"] or "",
                status=row["source"],
                created_at=row["created_at"],
                updated_at=updated,
                provenance=WorkspaceProvenance(
                    origin="human" if row["saved_by_user_id"] else "dialectic",
                    actor_user_id=row["saved_by_user_id"],
                    detail=row["source"],
                ),
                relationships=relationships,
                available_actions=actions,
                review_state="none",
                source_entity=sources,
            ))
        return objects

    async def research_briefs(self, room_id: UUID) -> list[WorkspaceObject]:
        """messages[metadata.source=deep_dive] → Research Brief.

        Projection only — no Brief table until editing or versioning demands
        one (§8.2). NOTE, observed while building C: §8.2 lists "Research
        question" among the Brief's fields, and llm/research.py never persists
        it — the question travels over DEEP_DIVE_STARTED and is gone. What
        survives is the brief itself, so that is what this projects. Carrying
        the question needs a write, which Release 1 does not make.
        """
        rows = await self.db.fetch(_BRIEFS_SQL, room_id, _PER_KIND_CAP)
        objects = []
        for row in rows:
            metadata = _jsonb(row["metadata"])
            relationships = []
            # The coordinate is the SLOT, which is what the envelope addresses
            # a proposal by. Building it from the kind instead produced a link
            # that resolved for exactly one of the five slots and dangled for
            # the rest -- a string that looks like an id is not an id, and
            # nothing complains until a surface follows one.
            for field, _kind, _payload in proposal_slots(metadata):
                relationships.append(WorkspaceRelationship(
                    relation="proposed", entity="proposal",
                    id=f"proposal:{row['id']}:{field}",
                ))
            tools = metadata.get("tools") or {}
            degraded = bool(tools.get("degraded"))
            objects.append(WorkspaceObject(
                id=f"research_brief:{row['id']}",
                kind="research_brief",
                room_id=room_id,
                branch_id=row["thread_id"],
                title=_clip(row["content"]),
                summary=str(row["content"] or "")[:600],
                status="degraded" if degraded else "completed",
                created_at=row["created_at"],
                updated_at=row["edited_at"] or row["created_at"],
                provenance=WorkspaceProvenance(
                    origin=_origin_for_speaker(row["speaker_type"]),
                    actor_user_id=row["user_id"],
                    detail="deep_dive",
                ),
                relationships=relationships,
                available_actions=["open_message", "open_room"],
                review_state="none",
                source_entity=[WorkspaceSourceRef(
                    entity="messages", id=str(row["id"]),
                )],
            ))
        return objects

    async def theses(self, room_id: UUID) -> list[WorkspaceObject]:
        """rooms.linked_book_id + trading_config → Thesis.

        A room holds at most one thesis (§12.2), so this is a 0-or-1 adapter.
        The `thesis_state_current` memory is FOLDED IN, not projected beside
        it — see THE SECOND TWIN at the top of this file. A Home room never
        yields one, because Home cannot own a thesis (§10.6) and therefore
        never carries a linked_book_id.
        """
        row = await self.db.fetchrow(_THESIS_SQL, room_id)
        if row is None:
            return []
        config = _jsonb(row["trading_config"])
        phase = str(config.get("cascadePhase") or "")
        pushed = row["last_trading_push_at"]
        updated = pushed or row["memory_updated_at"] or row["created_at"]
        sources = [WorkspaceSourceRef(
            entity="rooms", id=str(row["id"]), field="trading_config",
        )]
        if row["memory_id"] is not None:
            sources.append(WorkspaceSourceRef(
                entity="memories", id=str(row["memory_id"]), field="twin",
            ))
        source_event = None
        if row["event_id"] is not None:
            source_event = WorkspaceSourceRef(
                entity="events", id=str(row["event_id"]),
                field=row["event_type"],
            )
        return [WorkspaceObject(
            id=f"thesis:{row['linked_book_id']}",
            kind="thesis",
            room_id=room_id,
            branch_id=row["event_thread_id"],
            title=str(config.get("title") or row["linked_book_id"]),
            summary=(
                f"Cascade phase: {phase}" if phase
                else f"Thesis book {row['linked_book_id']}"
            ),
            status=phase or "bound",
            created_at=row["created_at"],
            updated_at=updated,
            provenance=WorkspaceProvenance(
                origin="desk", detail=row["linked_book_id"],
            ),
            relationships=[WorkspaceRelationship(
                relation="linked_book", entity="trading_book",
                id=row["linked_book_id"],
            )],
            available_actions=["open_thesis", "open_room"],
            review_state="none",
            source_entity=sources,
            source_event=source_event,
        )]

    async def commitments(self, room_id: UUID) -> list[WorkspaceObject]:
        """commitments (prediction | commitment | bet) → Commitment."""
        rows = await self.db.fetch(_COMMITMENTS_SQL, room_id, _PER_KIND_CAP)
        objects = []
        for row in rows:
            if row["status"] == "resolved":
                review = "resolved"
            elif row["is_due"]:
                review = "awaiting_human"
            else:
                review = "none"
            relationships = []
            if row["source_message_id"] is not None:
                relationships.append(WorkspaceRelationship(
                    relation="source_message", entity="messages",
                    id=str(row["source_message_id"]),
                ))
            actions = ["open_room"]
            if row["status"] == "active":
                actions.append("resolve")
            objects.append(WorkspaceObject(
                id=f"commitment:{row['id']}",
                kind="commitment",
                room_id=room_id,
                branch_id=row["thread_id"],
                title=row["claim"],
                summary=row["resolution_criteria"] or "",
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["resolved_at"] or row["created_at"],
                provenance=WorkspaceProvenance(
                    origin="human" if row["created_by_user_id"] else "dialectic",
                    actor_user_id=row["created_by_user_id"],
                    detail=row["category"] or "prediction",
                ),
                relationships=relationships,
                available_actions=actions,
                review_state=review,
                source_entity=[WorkspaceSourceRef(
                    entity="commitments", id=str(row["id"]),
                )],
            ))
        return objects

    async def proposals(self, room_id: UUID) -> list[WorkspaceObject]:
        """message metadata → Proposal, projected FROM the envelope.

        WHY delegate rather than read the metadata again: Task Group D's
        ProposalEnvelope is the one answer to "what is a proposal" — which
        slots count, which kind each is, whether the target is already gone.
        A second parse here would be a second answer, and the two would agree
        only until one of them was edited.

        The envelope's own review vocabulary maps onto the workspace object's:
        a proposal still open is what a human owes, everything else is settled.
        """
        envelopes = await ProposalEnvelopeService(self.db).build(room_id)
        objects = []
        for envelope in envelopes:
            payload = envelope.payload
            title = _clip(
                payload.get("statement") or payload.get("claim")
                or payload.get("title") or payload.get("url")
                or envelope.proposal_kind
            )
            relationships = [WorkspaceRelationship(
                relation="source_message", entity="messages",
                id=str(envelope.source_message_id),
            )]
            if envelope.target_object:
                relationships.append(WorkspaceRelationship(
                    relation="target_object", entity="workspace_object",
                    id=envelope.target_object,
                ))
            objects.append(WorkspaceObject(
                id=envelope.id,
                kind="proposal",
                room_id=envelope.room_id,
                branch_id=envelope.branch_id,
                title=title,
                summary=_clip(envelope.rationale, 300),
                status=envelope.status,
                created_at=envelope.created_at,
                updated_at=envelope.accepted_at or envelope.created_at,
                provenance=WorkspaceProvenance(
                    origin=(
                        "human" if envelope.created_by else "dialectic"
                    ),
                    actor_user_id=envelope.created_by,
                    detail=envelope.proposal_kind,
                ),
                relationships=relationships,
                available_actions=envelope.available_actions,
                review_state=(
                    "awaiting_human" if envelope.status == "proposed"
                    else _REVIEW_FOR_PROPOSAL_STATUS.get(
                        envelope.status, "none")
                ),
                source_entity=[WorkspaceSourceRef(
                    entity="messages", id=str(envelope.source_message_id),
                    field=envelope.id.split(":", 2)[2],
                )],
            ))
        return objects

    async def dossier(
        self, room_id: UUID, viewer_user_id: Optional[UUID] = None,
    ) -> list[WorkspaceObject]:
        """memories → Dossier entry, minus every twin (see THE TWIN RULE)."""
        rows = await self.db.fetch(
            _DOSSIER_SQL, room_id, viewer_user_id, _PER_KIND_CAP,
        )
        objects = []
        for row in rows:
            relationships = []
            if row["source_message_id"] is not None:
                relationships.append(WorkspaceRelationship(
                    relation="source_message", entity="messages",
                    id=str(row["source_message_id"]),
                ))
            objects.append(WorkspaceObject(
                id=f"dossier_entry:{row['id']}",
                kind="dossier_entry",
                room_id=room_id,
                branch_id=row["branch_id"],
                title=row["key"],
                summary=_clip(row["content"], 300),
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"] or row["created_at"],
                provenance=WorkspaceProvenance(
                    origin="human" if row["created_by_user_id"] else "dialectic",
                    actor_user_id=(
                        row["speaker_user_id"] or row["created_by_user_id"]
                    ),
                    detail=row["scope"],
                ),
                relationships=relationships,
                available_actions=["open_room", "inspect"],
                review_state="none",
                source_entity=[WorkspaceSourceRef(
                    entity="memories", id=str(row["id"]),
                )],
            ))
        return objects

    async def record_events(self, room_id: UUID) -> list[WorkspaceObject]:
        """messages + events → Record event (§6.4: speech AND operations).

        The Record is never rewritten by interpretation (§5.8), which is why
        this adapter reads the two append-only sources directly rather than
        any summary built over them.
        """
        rows = await self.db.fetch(_RECORD_SQL, room_id, _RECORD_CAP)
        objects = []
        for row in rows:
            is_message = row["source"] == "message"
            entity = "messages" if is_message else "events"
            objects.append(WorkspaceObject(
                id=f"record_event:{entity}:{row['id']}",
                kind="record_event",
                room_id=room_id,
                branch_id=row["thread_id"],
                title=_clip(row["body"]) if is_message else row["label"],
                summary=row["body"] or "",
                status=row["label"] or ("spoken" if is_message else "logged"),
                created_at=row["occurred_at"],
                updated_at=row["edited_at"] or row["occurred_at"],
                provenance=WorkspaceProvenance(
                    origin=(
                        _origin_for_speaker(row["speaker_type"])
                        if is_message else "system"
                    ),
                    actor_user_id=_as_uuid(row["user_id"]),
                    detail=row["label"],
                ),
                relationships=[],
                available_actions=(
                    ["open_message", "open_room"] if is_message
                    else ["inspect", "open_room"]
                ),
                review_state="none",
                source_entity=[WorkspaceSourceRef(
                    entity=entity, id=str(row["id"]),
                )],
                source_event=(
                    None if is_message else WorkspaceSourceRef(
                        entity="events", id=str(row["id"]), field=row["label"],
                    )
                ),
            ))
        return objects


def workspace_object_from_movement(
    movement: HomeActivityMovement,
) -> WorkspaceObject:
    """Home activity item → House movement, REUSING B's projection.

    WHY a pure function and not a query: home_activity.py already builds
    movement inside one snapshot, fenced by the Home membership intersection.
    A second query here would be a second copy of that fence — and the fence is
    the entire privacy invariant. The House hands its items over; this only
    changes their shape.

    The destination B computed travels as a relationship rather than being
    recomputed, so this adapter cannot become a second URL-grammar writer.
    """
    entity = "home_activity"
    return WorkspaceObject(
        id=f"house_movement:{movement.kind}:{movement.object_id}",
        kind="house_movement",
        room_id=movement.room_id,
        branch_id=movement.thread_id,
        title=movement.title,
        summary=movement.title,
        status=movement.state or "moved",
        created_at=movement.occurred_at,
        updated_at=movement.occurred_at,
        provenance=WorkspaceProvenance(origin="system", detail=movement.kind),
        relationships=[WorkspaceRelationship(
            relation="destination", entity="url", id=movement.destination,
        )],
        available_actions=(
            ["open_room", "open_branch"] if movement.thread_id
            else ["open_room"]
        ),
        review_state=(
            "awaiting_human" if movement.requires_judgment else "none"
        ),
        source_entity=[WorkspaceSourceRef(
            entity=entity,
            id=str(movement.object_id) if movement.object_id else "",
            field=movement.kind,
        )],
    )


class WorkspaceObjectProjection(BaseModel):
    generated_at: datetime
    room_id: UUID
    objects: list[WorkspaceObject]


async def build_projection(
    db, room_id: UUID, viewer_user_id: Optional[UUID] = None,
) -> WorkspaceObjectProjection:
    return WorkspaceObjectProjection(
        generated_at=datetime.now(timezone.utc),
        room_id=room_id,
        objects=await WorkspaceObjectService(db).build(room_id, viewer_user_id),
    )
