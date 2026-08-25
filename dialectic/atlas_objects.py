# atlas_objects.py — the cross-room map of what a viewer can reach.
#
# ARCHITECTURE: a semantic structure, not a graph engine (§1.4). This module
# builds the list/tree representation ONLY — nodes and edges as data. Any
# spatial rendering is a later, second view of the SAME projection; nothing
# here assumes one exists. Like workspace_objects.py and field_marks.py, this
# is READ-ONLY by construction: every statement below is a SELECT, and there
# is no write path anywhere in this module.
#
# THE FENCE IS PER-VIEWER, NOT ALL-MEMBERS-INTERSECTION (§5.4, §6.5). Home's
# projection (home_activity.py) is a SHARED surface, so it is fenced to the
# intersection of every current Home member's access — nobody sees a room
# someone else in the household cannot reach. Atlas is personal navigation:
# "Atlas authorization matches source-room authorization" (exit gate), so its
# fence is simply the CALLER'S OWN room_memberships. Every arm of every
# statement below is fenced by that same eligible-room array — an id array
# built from ONE query (`_ELIGIBLE_ROOMS_SQL`) and threaded, unmodified, into
# every subsequent read. A cross-room edge (Echo citations) is the one place
# this matters twice: BOTH endpoints must resolve inside the caller's own
# array, or a citation from a room the viewer cannot see would leak that
# room's title through the edge alone even though no node for it exists.
#
# BOUNDS ARE PER-PARTITION, IN SQL (§1.6). Every per-room statement ranks
# with `row_number() OVER (PARTITION BY room_id ...)` before any LIMIT, so
# one prolific room cannot evict every other room's rows the way a single
# global `ORDER BY … LIMIT` did in the Release 1 defect this rule exists to
# prevent (home_activity._MOVEMENT_SQL is the precedent copied here).
#
# NODE IDS REUSE workspace_objects.py's OWN CONVENTION wherever the same row
# is being projected (`reading:<id>`, `research_brief:<id>`,
# `thesis:<linked_book_id>`, `commitment:<id>`, `field_mark:<id>`) — not a
# coincidence: TG-B's Focus/object axis resolves an object by exactly that
# id shape, so an Atlas node for a reading and a workspace object for the
# SAME reading carry the SAME id, and "objects → the object axis" (§5.4)
# needs no second id scheme to bridge. `room` and `branch` are Atlas-only
# kinds (rooms and threads are never workspace objects), so they mint their
# own `room:<id>` / `branch:<id>` ids.
#
# UNRESOLVED WORK CONSUMES field_marks.py'S OWN SERVICE, NOT A REIMPLEMENTED
# DERIVATION. `FieldMarkService.build(room_id)` already fences and caps on
# room_id and derives the review axis correctly (confirm/contest/correct/
# split/merge/supersede, anti-reshuffle lineage). Reimplementing "is this
# mark still open" here in a second SQL statement would be exactly the
# "prompt exists in several copies" trap — two answers to one question that
# drift the moment field_marks.py's derivation rule changes. This module
# calls the service once per eligible room (bounded by the eligible-room
# array itself) and folds the result through `workspace_object_from_field_mark`
# — the same pure adapter workspace_objects.py ships for exactly this later
# consumer.
#
# CONTRADICTIONS ARE LABELED DERIVED PROXIES, NEVER INVENTED EDGES. The
# vocabulary reserves a `contradiction_proxy` kind, backed by only two real
# signals: a memory that was explicitly INVALIDATED (not merely superseded
# by an ordinary same-speaker restatement — `invalidation_reason IS NOT
# NULL` is the human's stated reason two facts conflicted) and a message
# whose `claim_check` verdict is `mixed`/`misrepresented` AND whose linked
# URL resolves to a real `reading_items` row in the same room. Production
# holds zero stored claim_check keys today (§6.6), so this arm returns
# nothing until claim_check actually fires — the SQL is still correct, and a
# fixture exercises it directly rather than waiting for that population.

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from field_marks import FieldMarkService
from geo_scopes import GeoScope, live_predicate as _geo_live_predicate, scope_from_row
from home_activity import COMMITMENT_DUE_WINDOW
from workspace_objects import workspace_object_from_field_mark

# The closed node vocabulary (§5.4's node list). A surface switches on these;
# an unlisted value is a bug, not an extension.
ATLAS_NODE_KINDS = (
    "room",
    "branch",
    "thesis",
    "reading",
    "research_brief",
    "commitment",
    "field_mark",
)

# The closed edge vocabulary — REAL provenance only (§5.4). `contradiction_proxy`
# is explicitly a LABELED DERIVED proxy, never a first-class assertion; the
# vocabulary reserves richer kinds for when field_marks' own
# `possible_contradiction` relation earns a dedicated edge, which this release
# does not build (do not invent edges the rows cannot back).
ATLAS_EDGE_KINDS = (
    "branch_genealogy",
    "echo_citation",
    "reading_source",
    "thesis_binding",
    "memory_supersession",
    "contradiction_proxy",
)

# Backstops, all applied inside SQL before any Python-side truncation (§1.6).
# Sized against §6.6's observed population (23 rooms, 296 messages, 425
# memories, 13 readings, 5 theses, 7 memory_references) with headroom for
# TG-G's seed scale (~50 rooms).
_ATLAS_ROOM_CAP = 200
_ATLAS_PER_ROOM_CAP = 25
_ATLAS_TOTAL_CAP = 400
_ATLAS_UNRESOLVED_PER_ROOM_CAP = 10
_ATLAS_UNRESOLVED_TOTAL_CAP = 100
_ATLAS_EDGE_CAP = 300


class AtlasRef(BaseModel):
    """Exactly which row an edge endpoint names. Mirrors
    workspace_objects.WorkspaceSourceRef / field_marks.FieldSubjectRef
    field-for-field (entity, id, field) without importing either — each
    projection module owns its own copy of this shape (field_marks.py's own
    docstring states the same rule for why)."""
    entity: str
    id: str
    field: Optional[str] = None


class AtlasNode(BaseModel):
    """One thing the viewer can navigate to, in one shape across seven kinds.

    A PROJECTION, never a copy — every field here is derived at read time
    from a row that already exists and owns its own storage.
    """
    id: str
    kind: str
    room_id: UUID
    branch_id: Optional[UUID] = None
    title: str
    summary: str = ""
    status: str = ""
    # True only for a commitment inside home_activity.COMMITMENT_DUE_WINDOW —
    # the same line the House and the workspace-object projection draw, named
    # once there so a second copy of "72 hours" cannot drift from it. The
    # frontend's "unresolved work" cross-cutting group is exactly the union of
    # `due` commitments and `field_mark` nodes (§5.4) — a filter over this
    # one field plus a kind check, not a second server-side grouping.
    due: bool = False
    created_at: datetime
    updated_at: datetime


class AtlasEdge(BaseModel):
    """One real-provenance relationship between two rows, never a rendered
    line — Atlas ships list/tree only this release (§1.4)."""
    kind: str
    source: AtlasRef
    target: AtlasRef
    label: str = ""


class AtlasProjection(BaseModel):
    generated_at: datetime
    nodes: list[AtlasNode]
    edges: list[AtlasEdge]
    # World Lens (migration 021): the live geometry in the viewer's eligible
    # rooms, fenced by the SAME array as every node. A scope names its
    # subject ({entity,id,field}); the World renderer joins that to a node
    # (`reading:<id>`, `room:<id>`, `field_mark:<id>`) client-side. Nodes
    # carry no geo field on purpose — "not geographically modeled" is the
    # absence of a scope, never a null a renderer might misread as (0,0).
    scopes: list[GeoScope] = []


# --- statements --------------------------------------------------------
#
# Every statement below is fenced on the SAME eligible-room array, built once
# by _ELIGIBLE_ROOMS_SQL and threaded through unmodified. No later query may
# rediscover a room through a broader join — the fence is the entire privacy
# invariant (§6.5), and it must hold in the SQL, never only in the Python
# that consumes it.

_GEO_SCOPES_SQL = f"""
WITH ranked AS (
    SELECT g.id, g.room_id, g.subject, g.kind, g.geometry, g.label,
           g.authority, g.provenance, g.source_state, g.observed_at,
           g.retrieved_at, g.expires_at, g.confirmed_by, g.confirmed_at,
           g.supersedes_id, g.revision_action, g.review_note,
           g.created_by, g.created_at,
           row_number() OVER (
               PARTITION BY g.room_id ORDER BY g.created_at DESC
           ) AS rn
    FROM geo_scopes g
    WHERE g.room_id = ANY($1::uuid[]) AND {_geo_live_predicate("g")}
)
SELECT * FROM ranked WHERE rn <= $2
ORDER BY created_at DESC
LIMIT $3
"""

_ELIGIBLE_ROOMS_SQL = """
SELECT room_id FROM room_memberships WHERE user_id = $1
ORDER BY joined_at
LIMIT $2
"""

_ROOMS_SQL = """
SELECT id, name, created_at
FROM rooms
WHERE id = ANY($1::uuid[])
ORDER BY created_at DESC
LIMIT $2
"""

_BRANCHES_SQL = """
WITH ranked AS (
    SELECT t.id, t.room_id, t.parent_thread_id, t.title, t.created_at,
           row_number() OVER (
               PARTITION BY t.room_id ORDER BY t.created_at DESC
           ) AS rn
    FROM threads t
    WHERE t.room_id = ANY($1::uuid[])
)
SELECT id, room_id, parent_thread_id, title, created_at
FROM ranked WHERE rn <= $2
ORDER BY created_at DESC
LIMIT $3
"""

_THESES_SQL = """
SELECT id AS room_id, linked_book_id, trading_config, created_at,
       last_trading_push_at
FROM rooms
WHERE id = ANY($1::uuid[]) AND linked_book_id IS NOT NULL
LIMIT $2
"""

_READINGS_SQL = """
WITH ranked AS (
    SELECT ri.id, ri.room_id, ri.title, ri.url, ri.source,
           ri.source_message_id, ri.created_at, m.thread_id AS branch_id,
           row_number() OVER (
               PARTITION BY ri.room_id ORDER BY ri.created_at DESC
           ) AS rn
    FROM reading_items ri
    LEFT JOIN messages m ON m.id = ri.source_message_id
    WHERE ri.room_id = ANY($1::uuid[])
)
SELECT id, room_id, title, url, source, source_message_id, branch_id,
       created_at
FROM ranked WHERE rn <= $2
ORDER BY created_at DESC
LIMIT $3
"""

_BRIEFS_SQL = """
WITH ranked AS (
    SELECT m.id, t.room_id, m.thread_id, m.content, m.created_at,
           row_number() OVER (
               PARTITION BY t.room_id ORDER BY m.created_at DESC
           ) AS rn
    FROM messages m
    JOIN threads t ON t.id = m.thread_id
    WHERE t.room_id = ANY($1::uuid[])
      AND NOT m.is_deleted
      AND m.metadata->>'source' = 'deep_dive'
)
SELECT id, room_id, thread_id, content, created_at
FROM ranked WHERE rn <= $2
ORDER BY created_at DESC
LIMIT $3
"""

# Mirrors home_activity._COMMITMENTS_SQL's due window exactly — COMMITMENT_DUE_
# WINDOW is imported, never re-typed, so the House and Atlas can never draw
# the "due" line in two different places.
_COMMITMENTS_SQL = f"""
WITH ranked AS (
    SELECT c.id, c.room_id, c.thread_id, c.claim, c.status, c.deadline,
           c.created_at,
           (c.status = 'active' AND c.deadline IS NOT NULL
            AND c.deadline <= NOW() + INTERVAL '{COMMITMENT_DUE_WINDOW}'
           ) AS is_due,
           row_number() OVER (
               PARTITION BY c.room_id
               ORDER BY COALESCE(c.deadline, c.created_at) DESC
           ) AS rn
    FROM commitments c
    WHERE c.room_id = ANY($1::uuid[])
)
SELECT id, room_id, thread_id, claim, status, deadline, created_at, is_due
FROM ranked WHERE rn <= $2
ORDER BY COALESCE(deadline, created_at) DESC
LIMIT $3
"""

# Echo citations (memory_references) — the one durable cross-room edge table.
# BOTH the source memory's room AND the target room must be in the caller's
# own eligible array: fencing only the source would still let an edge NAME a
# room (via target_room_id) the viewer cannot see, which is a title leak even
# though no node for that room exists in the projection.
_ECHO_SQL = """
SELECT mr.source_memory_id, mr.target_room_id, mr.target_thread_id,
       mr.target_message_id, mr.citation_context, mr.referenced_at
FROM memory_references mr
JOIN memories m ON m.id = mr.source_memory_id
WHERE m.room_id = ANY($1::uuid[]) AND mr.target_room_id = ANY($1::uuid[])
ORDER BY mr.referenced_at DESC
LIMIT $2
"""

_SUPERSESSION_SQL = """
WITH ranked AS (
    SELECT id, room_id, superseded_by_memory_id, invalidation_reason,
           updated_at,
           row_number() OVER (
               PARTITION BY room_id ORDER BY updated_at DESC
           ) AS rn
    FROM memories
    WHERE room_id = ANY($1::uuid[]) AND superseded_by_memory_id IS NOT NULL
)
SELECT id, room_id, superseded_by_memory_id, invalidation_reason
FROM ranked WHERE rn <= $2
ORDER BY updated_at DESC
LIMIT $3
"""

# The claim_check half of the contradiction proxy. `ri.url` match is a
# same-room lookup, not a cross-room one — the reading a message's linked
# article was actually filed as, if it was filed at all. No match, no edge
# (§5.4: "do not invent edges the rows cannot back").
_CONTRADICTION_SQL = """
SELECT m.id AS message_id, t.room_id,
       m.metadata->'claim_check'->>'verdict' AS verdict,
       ri.id AS reading_id
FROM messages m
JOIN threads t ON t.id = m.thread_id
LEFT JOIN reading_items ri
       ON ri.room_id = t.room_id
      AND ri.url = m.metadata->'claim_check'->>'url'
WHERE t.room_id = ANY($1::uuid[])
  AND NOT m.is_deleted
  AND m.metadata->'claim_check'->>'verdict' IN ('mixed', 'misrepresented')
ORDER BY m.created_at DESC
LIMIT $2
"""


def _jsonb(value: Any) -> dict:
    """A JSONB column as a dict, whichever way the connection hands it over
    (workspace_objects._jsonb's reasoning, duplicated rather than imported —
    each projection module owns its own copy)."""
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
    """First meaningful line, bounded. Titles are labels, not paragraphs
    (workspace_objects._clip, duplicated per house convention)."""
    for line in str(text or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:limit]
    return ""


class AtlasService:
    """Builds one viewer's cross-room Atlas projection inside one snapshot.

    Read-only by construction: every statement above is a SELECT, and this
    class holds no write path. Fenced per-viewer (§5.4) — the eligible-room
    array is the caller's OWN room_memberships, never an intersection.
    """

    def __init__(self, db):
        self.db = db

    async def build(self, viewer_user_id: UUID) -> AtlasProjection:
        # Same conditional as HomeActivityService.build(): production hands
        # this service a standalone acquired connection (an explicit
        # snapshot transaction is needed), while test fixtures already wrap
        # everything in a rollback transaction — asyncpg refuses isolation
        # options on a nested transaction, where the outer transaction
        # already IS the snapshot.
        if self.db.is_in_transaction():
            return await self._build(viewer_user_id)
        async with self.db.transaction(isolation="repeatable_read", readonly=True):
            return await self._build(viewer_user_id)

    async def _build(self, viewer_user_id: UUID) -> AtlasProjection:
        generated_at = datetime.now(timezone.utc)

        eligible = await self.db.fetch(
            _ELIGIBLE_ROOMS_SQL, viewer_user_id, _ATLAS_ROOM_CAP,
        )
        room_ids = [r["room_id"] for r in eligible]
        if not room_ids:
            return AtlasProjection(generated_at=generated_at, nodes=[], edges=[])

        room_rows = await self.db.fetch(_ROOMS_SQL, room_ids, _ATLAS_ROOM_CAP)
        branch_rows = await self.db.fetch(
            _BRANCHES_SQL, room_ids, _ATLAS_PER_ROOM_CAP, _ATLAS_TOTAL_CAP,
        )
        thesis_rows = await self.db.fetch(
            _THESES_SQL, room_ids, _ATLAS_ROOM_CAP,
        )
        reading_rows = await self.db.fetch(
            _READINGS_SQL, room_ids, _ATLAS_PER_ROOM_CAP, _ATLAS_TOTAL_CAP,
        )
        brief_rows = await self.db.fetch(
            _BRIEFS_SQL, room_ids, _ATLAS_PER_ROOM_CAP, _ATLAS_TOTAL_CAP,
        )
        commitment_rows = await self.db.fetch(
            _COMMITMENTS_SQL, room_ids, _ATLAS_PER_ROOM_CAP, _ATLAS_TOTAL_CAP,
        )
        echo_rows = await self.db.fetch(_ECHO_SQL, room_ids, _ATLAS_EDGE_CAP)
        supersession_rows = await self.db.fetch(
            _SUPERSESSION_SQL, room_ids, _ATLAS_PER_ROOM_CAP, _ATLAS_EDGE_CAP,
        )
        contradiction_rows = await self.db.fetch(
            _CONTRADICTION_SQL, room_ids, _ATLAS_EDGE_CAP,
        )
        scope_rows = await self.db.fetch(
            _GEO_SCOPES_SQL, room_ids, _ATLAS_PER_ROOM_CAP, _ATLAS_TOTAL_CAP,
        )

        nodes: list[AtlasNode] = []
        edges: list[AtlasEdge] = []

        for row in room_rows:
            nodes.append(AtlasNode(
                id=f"room:{row['id']}",
                kind="room",
                room_id=row["id"],
                title=row["name"] or "Untitled room",
                created_at=row["created_at"],
                updated_at=row["created_at"],
            ))

        # branch_id → row, used below both for AtlasNode.branch_id assignment
        # and to check a genealogy edge's PARENT is itself inside the capped,
        # fenced set before emitting an edge to it — a parent that fell
        # outside the per-room cap (or, defensively, outside the eligible
        # array) must not become an edge with no corresponding node.
        branch_by_id: dict[UUID, dict] = {row["id"]: row for row in branch_rows}
        for row in branch_rows:
            nodes.append(AtlasNode(
                id=f"branch:{row['id']}",
                kind="branch",
                room_id=row["room_id"],
                branch_id=row["id"],
                title=row["title"] or "Untitled branch",
                created_at=row["created_at"],
                updated_at=row["created_at"],
            ))
            parent_id = row["parent_thread_id"]
            if parent_id is not None and parent_id in branch_by_id:
                edges.append(AtlasEdge(
                    kind="branch_genealogy",
                    source=AtlasRef(entity="threads", id=str(row["id"])),
                    target=AtlasRef(entity="threads", id=str(parent_id)),
                ))

        for row in thesis_rows:
            config = _jsonb(row["trading_config"])
            book_id = row["linked_book_id"]
            updated = row["last_trading_push_at"] or row["created_at"]
            nodes.append(AtlasNode(
                id=f"thesis:{book_id}",
                kind="thesis",
                room_id=row["room_id"],
                title=str(config.get("title") or book_id),
                summary=str(config.get("cascadePhase") or ""),
                status=str(config.get("cascadePhase") or "bound"),
                created_at=row["created_at"],
                updated_at=updated,
            ))
            edges.append(AtlasEdge(
                kind="thesis_binding",
                source=AtlasRef(
                    entity="rooms", id=str(row["room_id"]), field="linked_book_id",
                ),
                target=AtlasRef(entity="rooms", id=str(row["room_id"])),
                label=book_id,
            ))

        for row in reading_rows:
            nodes.append(AtlasNode(
                id=f"reading:{row['id']}",
                kind="reading",
                room_id=row["room_id"],
                branch_id=row["branch_id"],
                title=row["title"] or row["url"],
                status=row["source"],
                created_at=row["created_at"],
                updated_at=row["created_at"],
            ))
            if row["source_message_id"] is not None:
                edges.append(AtlasEdge(
                    kind="reading_source",
                    source=AtlasRef(entity="reading_items", id=str(row["id"])),
                    target=AtlasRef(
                        entity="messages", id=str(row["source_message_id"]),
                    ),
                ))

        for row in brief_rows:
            nodes.append(AtlasNode(
                id=f"research_brief:{row['id']}",
                kind="research_brief",
                room_id=row["room_id"],
                branch_id=row["thread_id"],
                title=_clip(row["content"]),
                summary=str(row["content"] or "")[:300],
                status="completed",
                created_at=row["created_at"],
                updated_at=row["created_at"],
            ))

        for row in commitment_rows:
            nodes.append(AtlasNode(
                id=f"commitment:{row['id']}",
                kind="commitment",
                room_id=row["room_id"],
                branch_id=row["thread_id"],
                title=row["claim"],
                status=row["status"],
                due=bool(row["is_due"]),
                created_at=row["created_at"],
                updated_at=row["created_at"],
            ))

        # Unresolved work: field_marks' own service, per eligible room —
        # never a second derivation of "is this mark still open" (see the
        # module docstring). Collected across ALL rooms first, then ranked
        # globally, so the total cap falls on the OLDEST candidates rather
        # than on whichever room happened to be processed last.
        unresolved: list = []
        for room_id in room_ids:
            projection = await FieldMarkService(self.db).build(room_id)
            candidates = [
                m for m in projection.marks
                if m.relation == "unanswered_question" and m.review != "superseded"
            ]
            candidates.sort(key=lambda m: m.created_at, reverse=True)
            unresolved.extend(candidates[:_ATLAS_UNRESOLVED_PER_ROOM_CAP])
        unresolved.sort(key=lambda m: m.created_at, reverse=True)
        for mark in unresolved[:_ATLAS_UNRESOLVED_TOTAL_CAP]:
            obj = workspace_object_from_field_mark(mark)
            nodes.append(AtlasNode(
                id=obj.id,
                kind="field_mark",
                room_id=obj.room_id,
                branch_id=obj.branch_id,
                title=obj.title,
                summary=obj.summary,
                status=obj.status,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
            ))

        for row in echo_rows:
            if row["target_message_id"] is not None:
                target = AtlasRef(
                    entity="messages", id=str(row["target_message_id"]),
                )
            elif row["target_thread_id"] is not None:
                target = AtlasRef(
                    entity="threads", id=str(row["target_thread_id"]),
                )
            else:
                target = AtlasRef(entity="rooms", id=str(row["target_room_id"]))
            edges.append(AtlasEdge(
                kind="echo_citation",
                source=AtlasRef(
                    entity="memories", id=str(row["source_memory_id"]),
                ),
                target=target,
                label=row["citation_context"] or "",
            ))

        for row in supersession_rows:
            source = AtlasRef(entity="memories", id=str(row["id"]))
            target = AtlasRef(
                entity="memories", id=str(row["superseded_by_memory_id"]),
            )
            edges.append(AtlasEdge(
                kind="memory_supersession", source=source, target=target,
            ))
            # A contradiction proxy, not a second fact: an INVALIDATED memory
            # (a human's stated reason two facts conflicted) is a stronger
            # signal than an ordinary same-speaker restatement, which also
            # supersedes but carries no invalidation_reason.
            if row["invalidation_reason"]:
                edges.append(AtlasEdge(
                    kind="contradiction_proxy", source=source, target=target,
                    label=row["invalidation_reason"],
                ))

        for row in contradiction_rows:
            if row["reading_id"] is None:
                continue
            edges.append(AtlasEdge(
                kind="contradiction_proxy",
                source=AtlasRef(entity="messages", id=str(row["message_id"])),
                target=AtlasRef(
                    entity="reading_items", id=str(row["reading_id"]),
                ),
                label=row["verdict"] or "",
            ))

        return AtlasProjection(
            generated_at=generated_at, nodes=nodes, edges=edges,
            scopes=[scope_from_row(r) for r in scope_rows],
        )
