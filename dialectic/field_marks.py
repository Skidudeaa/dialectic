# field_marks.py — the room's reasoning, marked up.
#
# ARCHITECTURE: field_marks is a proofreader's-marks metaphor over one table
# (migration 017). Dialectic pencils in provisional structure as the room
# talks — a support, a contradiction, an open question — and a human's
# confirm/contest/correct restyles the mark rather than rewriting it. Every
# mark is a row; nothing here is a copy of anything else, and this module
# projects that table the same way workspace_objects.py projects seven other
# entities: READ-ONLY, one statement per read, fenced on room_id.
#
# APPEND-ONLY (§1.10, §2 item 16): no function in this module UPDATEs or
# DELETEs a field_marks row. Review state (`provisional | confirmed |
# contested | superseded`) is NOT a stored column changed in place — it is
# DERIVED here, at read time, from a mark's own review rows plus whatever
# later row names it as a supersedes_id ancestor. The partial unique index
# `idx_field_marks_dedup (room_id, dedup_key)` is the actual guarantee that a
# corrected mark is never re-asserted (§1.10) — this module's dedup_key
# formula (`compute_dedup_key`) is shared by the API's human-write path
# (api/field.py) and the inference job (llm/field_inference.py) precisely so
# a human's correction and a later inference candidate describing the SAME
# relationship collide on the SAME row.
#
# WHY THIS MODULE DOES NOT IMPORT FROM workspace_objects.py: the opposite
# dependency is unavoidable (workspace_objects.workspace_object_from_field_mark
# needs the FieldMark shape), and importing back would be a cycle. The
# precedent is home_activity.py, which workspace_objects.py already imports
# FROM without a reverse import — the OWNING module never depends on its own
# adapter. `FieldSubjectRef` below deliberately mirrors
# workspace_objects.WorkspaceSourceRef's shape (entity, id, field) rather than
# importing it, for the same reason.
#
# §14.4 GUARD, stated here because it is invisible from any test that only
# reads the API: spec §14.4's human-ratified judgments (accepted premise,
# declared consensus, decision, resolved tension, final definition, branch
# merge, rejection of a position, Shared Ledger change, memory invalidation,
# a claim that a participant changed position) are structurally unwritable by
# inference because NONE of them is a member of FIELD_RELATIONS below. This
# is the whole guard — there is no further enforcement to add, and no TODO:
# a candidate relation outside this tuple fails llm/field_inference.py's hard
# validation and is dropped before it reaches SQL.

import json
import re
from datetime import datetime, timezone
from typing import Any, NamedTuple, Optional
from uuid import UUID

from pydantic import BaseModel

from geo_scopes import live_predicate as geo_scope_live_predicate

# --- vocabularies, order-pinned (tests/test_workspace_contract.py pins order
# too, not just membership: these render as switch arms and lists) ----------

# §14.3's ten, with support/challenge split into two directed relations —
# twelve total after adding causal `context`. Comment-documented rather than
# a DB CHECK: the list may grow,
# and a migration-per-relation would be the wrong cost for adding a kind of
# mark.
FIELD_RELATIONS = (
    "contribution_type",
    "claim_group",
    "supports",
    "challenges",
    "context",
    "repeated_definition",
    "possible_contradiction",
    "emerging_position",
    "evidence_attachment",
    "branch_candidate",
    "unanswered_question",
    "candidate_synthesis",
)

# Matches the migration's CHECK constraint order exactly.
FIELD_ACTIONS = ("confirm", "contest", "correct", "supersede", "split", "merge")

FIELD_ORIGINS = ("explicit", "inferred")

# These are the only relations whose semantic roles may cross the Field/World/
# thesis boundary. Existing supports/challenges marks between ordinary Field
# subjects remain valid; the causal grammar is activated by a `rooms` subject.
FIELD_CAUSAL_RELATIONS = ("supports", "challenges", "context")

_THESIS_NODE_FIELD = re.compile(r"^thesis_node:([^:]+):([^:]+)$")

# The independent REVIEW axis (§1.3, §14.2) — never conflated with
# deliberative_status, and never implying the marked proposition is true.
FIELD_REVIEW_STATES = ("provisional", "confirmed", "contested", "superseded")

# Matches the migration's deliberative_status CHECK constraint order.
FIELD_DELIBERATIVE_STATUSES = ("active", "accepted", "rejected", "resolved", "withdrawn")

# Which review actions retire a mark (the reader treats these as terminal
# unless a later confirm/contest reopens a bare 'supersede' — see the
# derivation docstring below for why 'correct'/'split'/'merge' cannot be
# reopened this way and 'supersede' alone can).
_SUPERSEDING_ACTIONS = ("supersede", "correct", "split", "merge")

# One statement, fenced on room_id, capped in the SQL itself (§1.6). Ranked
# by recency so a very active room's oldest history — not its live edge — is
# what falls outside the cap.
_FIELD_MARKS_CAP = 500

_FIELD_MARKS_SQL = """
SELECT id, room_id, thread_id, mark_kind, relation, action, origin,
       deliberative_status, subjects, target_mark_id, title, payload,
       supersedes_id, caused_by_id, actor_user_id, provenance, created_at
FROM field_marks
WHERE room_id = $1
ORDER BY created_at DESC
LIMIT $2
"""

_TARGET_ROW_SQL = """
SELECT id, room_id, thread_id, mark_kind, relation, subjects, title, payload
FROM field_marks
WHERE id = $1 AND room_id = $2
"""

_SUCCESSOR_EXISTS_SQL = """
SELECT EXISTS (SELECT 1 FROM field_marks WHERE supersedes_id = $1)
"""

_REVIEWS_FOR_TARGET_SQL = """
SELECT id, action, created_at
FROM field_marks
WHERE mark_kind = 'review' AND target_mark_id = $1
"""

_FULL_MARK_SQL = """
SELECT id, room_id, thread_id, mark_kind, relation, action, origin,
       deliberative_status, subjects, target_mark_id, title, payload,
       supersedes_id, caused_by_id, actor_user_id, provenance, created_at
FROM field_marks
WHERE id = $1 AND room_id = $2 AND mark_kind = 'relation'
"""

_REVIEWS_FULL_SQL = """
SELECT id, action, actor_user_id, payload, created_at
FROM field_marks
WHERE mark_kind = 'review' AND target_mark_id = $1
"""

_CAUSAL_GEO_WHERE_SQL = """
room_id = $1
AND mark_kind = 'relation'
AND relation = ANY($2::text[])
AND jsonb_array_length(subjects) = 2
AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(subjects) AS subject
    WHERE subject->>'entity' = 'geo_scopes'
      AND subject->>'id' = ANY($3::text[])
)
AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(subjects) AS subject
    WHERE subject->>'entity' = 'rooms'
      AND subject->>'id' = $1::text
      AND subject->>'field' ~ '^thesis_node:[^:]+:[^:]+$'
)
"""

_CAUSAL_GEO_COUNT_SQL = f"""
SELECT count(*) FROM field_marks WHERE {_CAUSAL_GEO_WHERE_SQL}
"""

_CAUSAL_GEO_IDS_SQL = f"""
SELECT id FROM field_marks
WHERE {_CAUSAL_GEO_WHERE_SQL}
ORDER BY created_at DESC, id DESC
LIMIT $4
"""

# Every entity a subject ref may name, and how to check it belongs to the
# room. Table names come from this fixed dict, never from a caller, so the
# f-string below is not a SQL-injection surface. Shared by the API's
# human-write validation (422) and the inference job's hard validation
# (§5.1: "the model cannot mint provenance") — one definition, not two.
_SUBJECT_ENTITY_TABLES = {
    "messages": ("messages m JOIN threads t ON t.id = m.thread_id", "t.room_id", "m.id"),
    "reading_items": ("reading_items", "room_id", "id"),
    "memories": ("memories", "room_id", "id"),
    "commitments": ("commitments", "room_id", "id"),
    "field_marks": ("field_marks", "room_id", "id"),
    # World Lens (migration 021). The fourth element is an extra predicate:
    # only geometry a human confirmed or a source reported may anchor a mark.
    # A machine_proposed scope is the participant's guess and stays outside
    # the Field until a person confirms it — the same fail-closed rule §14.4
    # applies to relations, applied to coordinates. The live rule itself is
    # The owner module supplies the canonical alias-aware live predicate; the
    # Field adds only its authority requirement.
    "geo_scopes": (
        "geo_scopes", "room_id", "id",
        "AND authority <> 'machine_proposed'"
        f" AND {geo_scope_live_predicate('geo_scopes')}",
    ),
}


class FieldSubjectRef(BaseModel):
    """Exactly where a mark points. Mirrors workspace_objects.WorkspaceSourceRef
    field-for-field (entity, id, field) without importing it — see the module
    docstring for why the import would cycle."""
    entity: str
    id: str
    field: Optional[str] = None


class CausalFieldRoles(NamedTuple):
    """Semantic roles for one World-to-thesis mark, independent of JSON order."""
    evidence: dict
    target: dict
    book_id: str
    node_id: str


class FieldReview(BaseModel):
    """One human action on a mark. Never itself reviewed — reviews are the
    leaves of the append-only tree, not a target of a target."""
    id: UUID
    action: str
    actor_user_id: Optional[UUID] = None
    note: Optional[str] = None
    created_at: datetime


class FieldMark(BaseModel):
    """One relation-kind row, exactly as a surface renders it.

    `id` is `field_mark:<uuid>`, matching every other workspace-object id
    convention. `review` is DERIVED (never a stored column read verbatim) —
    see `_derive_review_state`. `supersedes_id`/`caused_by_id` stay bare row
    ids (not the `field_mark:` prefix) because they are foreign keys into
    this SAME table, not cross-entity references; a caller that needs the
    prefixed form computes `f"field_mark:{supersedes_id}"` itself.
    """
    id: str
    room_id: UUID
    thread_id: Optional[UUID] = None
    relation: str
    origin: Optional[str] = None
    review: str
    deliberative_status: str
    subjects: list[FieldSubjectRef] = []
    title: str
    payload: dict = {}
    supersedes_id: Optional[UUID] = None
    caused_by_id: Optional[UUID] = None
    actor_user_id: Optional[UUID] = None
    provenance: str
    created_at: datetime
    reviews: list[FieldReview] = []


class FieldProjection(BaseModel):
    generated_at: datetime
    room_id: UUID
    marks: list[FieldMark]


class CausalGeoBindingProjection(BaseModel):
    """A bounded, exact-count view of causal marks for named scope revisions."""

    generated_at: datetime
    room_id: UUID
    marks: list[FieldMark]
    total: int
    omitted: int
    complete: bool


def _jsonb(value: Any) -> dict:
    """A JSONB column as a dict, whichever way the connection hands it over
    (workspace_objects._jsonb's reasoning, duplicated rather than imported —
    each projection module owns its own copy, same as proposal_envelope's)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _jsonb_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _subject_token(subject: dict) -> str:
    token = f"{subject.get('entity')}:{subject.get('id')}"
    field = subject.get("field")
    if field:
        token += f"#{field}"
    return token


def compute_dedup_key(relation: str, subjects: list[dict]) -> str:
    """The idempotency key inference re-asserts against (§1.10).

    Used IDENTICALLY for an inference candidate and a human-written
    correct/split/merge replacement, so a human's correction and a later
    inference candidate describing the same relationship collide on the same
    row — the ON CONFLICT DO NOTHING that makes a correction durable is only
    correct if both writers compute this the same way.
    """
    tokens = sorted(_subject_token(s) for s in subjects)
    return f"{relation}|{','.join(tokens)}"


def causal_subject_roles(
    relation: Optional[str], subjects: list[dict],
) -> Optional[CausalFieldRoles]:
    """Resolve causal roles by entity, never by subject-array position.

    A room subject opts the mark into this strict grammar. Without one, the
    pre-existing Field subject rules apply unchanged (including ordinary
    supports/challenges relations between messages or marks).
    """
    room_subjects = [s for s in subjects if s.get("entity") == "rooms"]
    if not room_subjects:
        return None
    if relation not in FIELD_CAUSAL_RELATIONS:
        raise ValueError("room thesis subjects require a causal relation")
    scope_subjects = [s for s in subjects if s.get("entity") == "geo_scopes"]
    if len(subjects) != 2 or len(room_subjects) != 1 or len(scope_subjects) != 1:
        raise ValueError("causal marks require exactly one scope and one room target")
    field = room_subjects[0].get("field")
    match = _THESIS_NODE_FIELD.fullmatch(field) if isinstance(field, str) else None
    if match is None:
        raise ValueError("room target field must be thesis_node:<book-id>:<node-id>")
    return CausalFieldRoles(
        evidence=scope_subjects[0],
        target=room_subjects[0],
        book_id=match.group(1),
        node_id=match.group(2),
    )


async def resolve_subjects_in_room(
    db, room_id: UUID, subjects: list[dict], relation: Optional[str] = None,
    *, allow_causal: bool = False,
) -> bool:
    """Every subject ref resolves to a real row IN THIS ROOM, checked in SQL.

    Client payloads and model output are documents, not trust boundaries
    (§5.1): a subject naming an entity/id this room does not own must fail
    closed, never be trusted because the shape looked right.
    """
    if not subjects:
        return False
    try:
        causal_roles = causal_subject_roles(relation, subjects)
    except ValueError:
        return False
    # Only the human Field API performs the authenticated room/book/node
    # structure proof. Every other caller, especially model inference, stays
    # fail-closed even when the raw subject rows and grammar are valid.
    if causal_roles is not None and not allow_causal:
        return False
    for subject in subjects:
        entity = subject.get("entity")
        if entity == "rooms":
            try:
                subject_id = UUID(str(subject.get("id")))
            except (TypeError, ValueError):
                return False
            if subject_id != room_id:
                return False
            if not await db.fetchval("SELECT 1 FROM rooms WHERE id = $1", room_id):
                return False
            continue
        table = _SUBJECT_ENTITY_TABLES.get(entity)
        if table is None:
            return False
        source, room_col, id_col = table[:3]
        extra = table[3] if len(table) > 3 else ""
        try:
            subject_id = UUID(str(subject.get("id")))
        except (TypeError, ValueError):
            return False
        found = await db.fetchval(
            f"SELECT 1 FROM {source} WHERE {id_col} = $1 AND {room_col} = $2 {extra}",
            subject_id, room_id,
        )
        if not found:
            return False
    return True


def _derive_review_state(has_named_successor: bool, reviews: list[dict]) -> str:
    """The derived review rule (§5.1), as one pure function so the room-wide
    build() and the single-mark API guard (`current_review_state`) cannot
    drift into two different answers.

    `reviews` is unsorted; this sorts by (created_at, id) itself so a caller
    never has to remember to.

    WHY 'supersede' alone can be undone by a later confirm/contest and
    'correct'/'split'/'merge' cannot: the three that create a replacement
    row are permanently anchored via `has_named_successor` (the successor
    exists forever, append-only), while a bare 'supersede' has no successor
    row at all — its retirement lives ONLY in "latest review is supersede",
    so a later confirm/contest genuinely becomes the new latest and reopens
    it. That is a deliberate reading of "this question is already answered":
    revivable, not a lineage fork.
    """
    ordered = sorted(reviews, key=lambda r: (r["created_at"], str(r["id"])))
    latest = ordered[-1] if ordered else None
    if has_named_successor or (latest is not None and latest["action"] in _SUPERSEDING_ACTIONS):
        return "superseded"
    if latest is not None and latest["action"] == "confirm":
        return "confirmed"
    if latest is not None and latest["action"] == "contest":
        return "contested"
    # No reviews at all: provisional — INCLUDING an explicit human relation
    # with zero reviews. Its `origin` axis already says a human asserted it;
    # confirmed-at-birth is not a thing (§14.2's axes stay independent).
    return "provisional"


async def build_single_mark(db, room_id: UUID, mark_id: UUID) -> Optional[FieldMark]:
    """One mark with derived review + inline review history, by targeted
    queries — the write path's response builder (api/field.py).

    WHY not the room-wide build(): that projection is capped at
    `_FIELD_MARKS_CAP` newest rows, so a review of a mark just past the cap
    would COMMIT and then vanish from the projection — the 200 response must
    carry the reviewed mark regardless of where it sits in the room's
    history, and a per-review rebuild of 500 rows is also wasted work.
    Reuses the SAME `_derive_review_state` as build() and
    `current_review_state`, so a third caller cannot drift into a different
    answer.
    """
    row = await db.fetchrow(_FULL_MARK_SQL, mark_id, room_id)
    if row is None:
        return None
    has_successor = bool(await db.fetchval(_SUCCESSOR_EXISTS_SQL, mark_id))
    reviews = [dict(r) for r in await db.fetch(_REVIEWS_FULL_SQL, mark_id)]
    review_state = _derive_review_state(has_successor, reviews)
    return _to_field_mark(dict(row), review_state, reviews)


async def current_review_state(db, mark_id: UUID) -> str:
    """The single-mark version of the derivation above, for the API's
    pre-write guards (404/409 semantics) — two small targeted queries
    instead of the room-wide build(), reusing the SAME `_derive_review_state`
    so the write-time guard and the read-time projection can never disagree
    about what "already superseded" means.
    """
    has_successor = bool(await db.fetchval(_SUCCESSOR_EXISTS_SQL, mark_id))
    reviews = [dict(r) for r in await db.fetch(_REVIEWS_FOR_TARGET_SQL, mark_id)]
    return _derive_review_state(has_successor, reviews)


def _root_anchor(row_id: UUID, rows_by_id: dict) -> dict:
    """Follow supersedes_id to the chain head — the anti-reshuffle ordering
    rule (§5.1): a correction's replacement renders in its ANCESTOR's
    position, never at the end. `seen` guards a cycle even though append-only
    lineage should never produce one; a defensive stop costs nothing here."""
    seen = {row_id}
    current = rows_by_id[row_id]
    nxt = current["supersedes_id"]
    while nxt is not None and nxt in rows_by_id and nxt not in seen:
        seen.add(nxt)
        current = rows_by_id[nxt]
        nxt = current["supersedes_id"]
    return current


def _to_field_mark(row: dict, review_state: str, reviews: list[dict]) -> FieldMark:
    return FieldMark(
        id=f"field_mark:{row['id']}",
        room_id=row["room_id"],
        thread_id=row["thread_id"],
        relation=row["relation"],
        origin=row["origin"],
        review=review_state,
        deliberative_status=row["deliberative_status"],
        subjects=[FieldSubjectRef(**s) for s in _jsonb_list(row["subjects"])],
        title=row["title"] or "",
        payload=_jsonb(row["payload"]),
        supersedes_id=row["supersedes_id"],
        caused_by_id=row["caused_by_id"],
        actor_user_id=row["actor_user_id"],
        provenance=row["provenance"],
        created_at=row["created_at"],
        reviews=[
            FieldReview(
                id=r["id"],
                action=r["action"],
                actor_user_id=r["actor_user_id"],
                note=_jsonb(r["payload"]).get("note"),
                created_at=r["created_at"],
            )
            for r in sorted(reviews, key=lambda r: (r["created_at"], str(r["id"])))
        ],
    )


class FieldMarkService:
    """Projects one room's field_marks into FieldMark shapes.

    Read-only by construction: the only statement here is a SELECT, fenced
    on room_id, capped at `_FIELD_MARKS_CAP` — the house rule every projection
    in this codebase follows (workspace_objects.py, home_activity.py).
    """

    def __init__(self, db):
        self.db = db

    async def causal_geo_bindings(
        self, room_id: UUID, scope_ids: set[UUID], *, limit: int = 50,
    ) -> CausalGeoBindingProjection:
        """Read causal Field marks for specific room-owned scope revisions.

        This does not inherit the room-wide 500-row projection cap. The exact
        matching count and bounded result are reported separately so a caller
        can never confuse omitted history with no binding.
        """
        if not scope_ids:
            return CausalGeoBindingProjection(
                generated_at=datetime.now(timezone.utc), room_id=room_id,
                marks=[], total=0, omitted=0, complete=True,
            )
        if len(scope_ids) > 50:
            raise ValueError("causal scope lookup accepts at most 50 revisions")
        if limit < 1 or limit > 100:
            raise ValueError("causal scope lookup limit must be between 1 and 100")
        relations = list(FIELD_CAUSAL_RELATIONS)
        identifiers = [str(scope_id) for scope_id in sorted(scope_ids)]
        total = int(await self.db.fetchval(
            _CAUSAL_GEO_COUNT_SQL, room_id, relations, identifiers,
        ))
        rows = await self.db.fetch(
            _CAUSAL_GEO_IDS_SQL, room_id, relations, identifiers, limit,
        )
        marks: list[FieldMark] = []
        for row in rows:
            mark = await build_single_mark(self.db, room_id, row["id"])
            if mark is not None:
                marks.append(mark)
        omitted = max(0, total - len(marks))
        return CausalGeoBindingProjection(
            generated_at=datetime.now(timezone.utc), room_id=room_id,
            marks=marks, total=total, omitted=omitted, complete=omitted == 0,
        )

    async def build(self, room_id: UUID) -> FieldProjection:
        rows = [dict(r) for r in await self.db.fetch(
            _FIELD_MARKS_SQL, room_id, _FIELD_MARKS_CAP,
        )]
        rows_by_id = {row["id"]: row for row in rows}

        reviews_by_target: dict[UUID, list[dict]] = {}
        successors_by_target: set = set()
        for row in rows:
            if row["mark_kind"] == "review":
                reviews_by_target.setdefault(row["target_mark_id"], []).append(row)
            elif row["supersedes_id"] is not None:
                successors_by_target.add(row["supersedes_id"])

        entries = []
        for row in rows:
            if row["mark_kind"] != "relation":
                continue
            reviews = reviews_by_target.get(row["id"], [])
            review_state = _derive_review_state(
                row["id"] in successors_by_target, reviews,
            )
            root = _root_anchor(row["id"], rows_by_id)
            sort_key = (root["created_at"], root["id"], row["created_at"], row["id"])
            entries.append((sort_key, _to_field_mark(row, review_state, reviews)))

        entries.sort(key=lambda pair: pair[0])
        return FieldProjection(
            generated_at=datetime.now(timezone.utc),
            room_id=room_id,
            marks=[mark for _, mark in entries],
        )
