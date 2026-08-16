# api/field.py — the Field's write door: human review of a room's marks.
#
# ARCHITECTURE: GET here is a thin wrapper over field_marks.FieldMarkService,
# same shape as api/workspace.py's GET. The POST is this router's entire
# reason to exist (§2 item 15: "api/workspace.py stays write-free — Field
# reviews get their own router"): confirm/contest/correct/split/merge/
# supersede each write into field_marks in ONE transaction, attributed to the
# caller in the same insert as the action (acceptance_stamp's rule,
# proposal_envelope.py:127 — no review can be "by nobody"), and NEVER
# UPDATE or DELETE an existing row (§1.10, §2 item 16).
#
# WHY the same two credentials as every other room endpoint: `_authorize`
# below is copied from api/workspace.py:50 verbatim — a Field mark is exactly
# as sensitive as the room it reasons about.
#
# ONE WRITE ROUTE: the POST is the only mutation this router exposes. A test
# asserts that directly (tests/test_field_api.py), mirroring
# test_workspace_api.py's read-only assertion in reverse.

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from field_marks import (
    FIELD_ACTIONS,
    FIELD_RELATIONS,
    FieldMark,
    FieldMarkService,
    FieldProjection,
    FieldReview,
    FieldSubjectRef,
    build_single_mark,
    compute_dedup_key,
    current_review_state,
    resolve_subjects_in_room,
)
from models import EventType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["field"])

_db_pool = None


def set_field_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


async def _authorize(room_id: UUID, token: str, user_id: UUID, db) -> None:
    """Both credentials, exactly as every other room endpoint requires them
    (copied from api/workspace.py:50)."""
    room = await db.fetchrow(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2", room_id, token,
    )
    if not room:
        raise HTTPException(status_code=401, detail="Invalid room token")
    member = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    )
    if not member:
        raise HTTPException(
            status_code=403, detail="User is not a member of this room",
        )


# Actions that require the target to still be active; a replacement is
# lineage, not an edit, so re-correcting an already-superseded mark is
# refused rather than forking two replacement chains from one ancestor.
_TERMINAL_GUARDED_ACTIONS = ("correct", "split", "merge", "supersede")

_TARGET_SQL = """
SELECT id, room_id, thread_id, mark_kind, relation, title
FROM field_marks
WHERE id = $1 AND room_id = $2
"""

_INSERT_REVIEW_SQL = """
INSERT INTO field_marks
    (id, room_id, mark_kind, action, target_mark_id, actor_user_id,
     provenance, created_at, payload)
VALUES ($1, $2, 'review', $3, $4, $5, 'human', $6, $7)
"""

_INSERT_RELATION_SQL = """
INSERT INTO field_marks
    (id, room_id, thread_id, mark_kind, relation, origin, provenance,
     subjects, title, payload, supersedes_id, caused_by_id, actor_user_id,
     created_at, dedup_key)
VALUES ($1, $2, $3, 'relation', $4, 'explicit', 'human',
        $5, $6, $7, $8, $9, $10, $11, $12)
"""

# Repeats idx_field_marks_dedup's OWN partial predicate. Postgres will not
# infer a match against a partial unique index otherwise — it raises
# InvalidColumnReferenceError ("no unique or exclusion constraint matching the
# ON CONFLICT specification") rather than deduplicating. Same clause as
# llm/field_inference._INSERT_CANDIDATE_SQL, for the same reason.
_ON_CONFLICT_DEDUP = """
ON CONFLICT (room_id, dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING
"""

_INSERT_EVENT_SQL = """
INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""


class FieldReplacementRequest(BaseModel):
    relation: str
    subjects: list[FieldSubjectRef] = Field(min_length=1)
    title: str = ""
    payload: dict = {}


class FieldReviewRequest(BaseModel):
    action: str
    note: Optional[str] = None
    replacement: Optional[FieldReplacementRequest] = None
    replacements: Optional[list[FieldReplacementRequest]] = None
    merge_ids: Optional[list[UUID]] = None


class FieldReviewResponse(BaseModel):
    review: FieldReview
    replacements: list[FieldMark]
    mark: FieldMark


@router.get("/rooms/{room_id}/field", response_model=FieldProjection)
async def get_field(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> FieldProjection:
    """Every mark in the room, with derived review and inline review history
    — Focus needs both (§5.1). Projects; never writes."""
    await _authorize(room_id, token, current_user.user_id, db)
    return await FieldMarkService(db).build(room_id)


class FieldMarkCreateRequest(BaseModel):
    """A mark a human writes from nothing.

    Deliberately the same four fields as FieldReplacementRequest — a mark is
    a mark, whether it arrives as a correction of the machine's guess or as
    somebody's own observation. `thread_id` is optional because a mark about
    a reading or a memory belongs to no particular branch.
    """
    relation: str
    subjects: list[FieldSubjectRef] = Field(min_length=1)
    title: str = ""
    payload: dict = {}
    thread_id: Optional[UUID] = None


@router.post("/rooms/{room_id}/field/marks", response_model=FieldMark, status_code=201)
async def create_field_mark(
    room_id: UUID,
    request: FieldMarkCreateRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> FieldMark:
    """A human originates a mark — the door the Field never had.

    WHY it did not exist: Release 3 shipped review (confirm/contest/correct/
    supersede/split/merge), which acts on a mark the INFERENCE engine already
    proposed. Production bears out the consequence exactly — 85 marks, every
    one `origin='inferred'`, and not a single human review in the room's
    whole history. A human could disagree with the machine's reading and
    could not say anything the machine had not thought of first.

    The INSERT is the one already used for correction replacements
    (`_INSERT_RELATION_SQL`, `origin='explicit'`, `provenance='human'`), so
    this adds a door rather than a second way to write a mark.

    ON CONFLICT DO NOTHING repeats the partial index's own WHERE predicate —
    the index is `WHERE dedup_key IS NOT NULL`, and an ON CONFLICT that omits
    it does not match the index at all. Re-marking the same relation over the
    same subjects is idempotent, which is what makes a highlighter safe to
    double-tap.
    """
    await _authorize(room_id, token, current_user.user_id, db)

    if request.relation not in FIELD_RELATIONS:
        raise HTTPException(
            status_code=422, detail=f"Unknown relation: {request.relation}",
        )
    subjects = [s.model_dump() for s in request.subjects]
    # Client payloads are documents, not trust boundaries (§5.1): a subject
    # naming a row this room does not own fails closed.
    if not await resolve_subjects_in_room(db, room_id, subjects):
        raise HTTPException(
            status_code=422,
            detail="subjects do not resolve to rows in this room",
        )
    if request.thread_id is not None:
        owns_thread = await db.fetchval(
            "SELECT 1 FROM threads WHERE id = $1 AND room_id = $2",
            request.thread_id, room_id,
        )
        if not owns_thread:
            raise HTTPException(
                status_code=422, detail="thread does not belong to this room",
            )

    now = datetime.now(timezone.utc)
    mark_id = uuid4()
    dedup_key = compute_dedup_key(request.relation, subjects)

    async with db.transaction():
        await db.execute(
            _INSERT_RELATION_SQL + _ON_CONFLICT_DEDUP,
            mark_id, room_id, request.thread_id, request.relation, subjects,
            request.title, request.payload, None, None,
            current_user.user_id, now, dedup_key,
        )
        # DO NOTHING means an identical mark already exists; the caller asked
        # for that mark, so return it rather than a 409 they cannot act on.
        existing_id = await db.fetchval(
            "SELECT id FROM field_marks WHERE room_id = $1 AND dedup_key = $2",
            room_id, dedup_key,
        )
        resolved_id = existing_id or mark_id
        await db.execute(
            _INSERT_EVENT_SQL, uuid4(), now, EventType.FIELD_MARK_CREATED.value,
            room_id, request.thread_id, current_user.user_id,
            {"mark_id": str(resolved_id), "relation": request.relation,
             "origin": "explicit"},
        )

    mark = await build_single_mark(db, room_id, resolved_id)
    if mark is None:
        raise HTTPException(status_code=500, detail="mark did not persist")
    return mark


async def _validate_replacement(db, room_id: UUID, replacement: FieldReplacementRequest) -> None:
    if replacement.relation not in FIELD_RELATIONS:
        raise HTTPException(
            status_code=422, detail=f"Unknown relation: {replacement.relation}",
        )
    subjects = [s.model_dump() for s in replacement.subjects]
    # Client payloads are documents, not trust boundaries (§5.1) — every
    # subject must resolve to a real row in THIS room before anything writes.
    if not await resolve_subjects_in_room(db, room_id, subjects):
        raise HTTPException(
            status_code=422,
            detail="replacement subjects do not resolve to rows in this room",
        )


@router.post(
    "/rooms/{room_id}/field/marks/{mark_id}/review",
    response_model=FieldReviewResponse,
)
async def review_field_mark(
    room_id: UUID,
    mark_id: UUID,
    request: FieldReviewRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> FieldReviewResponse:
    """One human action on one mark. All writes land in ONE transaction; on
    any failure nothing lands (§5.1). Attribution follows acceptance_stamp's
    rule: who + when written in the same insert as the action.
    """
    await _authorize(room_id, token, current_user.user_id, db)

    if request.action not in FIELD_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown action: {request.action}")

    target = await db.fetchrow(_TARGET_SQL, mark_id, room_id)
    if target is None or target["mark_kind"] != "relation":
        raise HTTPException(status_code=404, detail="Mark not found")

    state = await current_review_state(db, mark_id)
    if request.action in _TERMINAL_GUARDED_ACTIONS and state == "superseded":
        raise HTTPException(status_code=409, detail=f"mark is already {state}")
    if request.action == "confirm" and state == "confirmed":
        raise HTTPException(status_code=409, detail=f"mark is already {state}")
    if request.action == "contest" and state == "contested":
        raise HTTPException(status_code=409, detail=f"mark is already {state}")

    # Gather + validate every merge source up front, before any write —
    # a mid-split/mid-merge failure must leave zero rows, and validating
    # after starting the transaction would mean rolling back on a 404/409
    # that a pre-check could have caught for free.
    merge_targets: list = []
    if request.action == "merge":
        merge_ids = list(dict.fromkeys([mark_id, *(request.merge_ids or [])]))
        if len(merge_ids) < 2:
            raise HTTPException(
                status_code=422, detail="merge needs at least one other mark",
            )
        for other_id in merge_ids:
            if other_id == mark_id:
                merge_targets.append(target)
                continue
            other = await db.fetchrow(_TARGET_SQL, other_id, room_id)
            if other is None or other["mark_kind"] != "relation":
                raise HTTPException(
                    status_code=404, detail=f"Merge source not found: {other_id}",
                )
            other_state = await current_review_state(db, other_id)
            if other_state == "superseded":
                raise HTTPException(
                    status_code=409,
                    detail=f"merge source {other_id} is already superseded",
                )
            merge_targets.append(other)

    replacement_requests: list[FieldReplacementRequest] = []
    if request.action == "correct":
        if request.replacement is None:
            raise HTTPException(status_code=422, detail="correct needs a replacement")
        replacement_requests = [request.replacement]
    elif request.action == "split":
        if not request.replacements:
            raise HTTPException(status_code=422, detail="split needs replacements")
        replacement_requests = request.replacements
    elif request.action == "merge":
        if request.replacement is None:
            raise HTTPException(status_code=422, detail="merge needs a replacement")
        replacement_requests = [request.replacement]

    for replacement in replacement_requests:
        await _validate_replacement(db, room_id, replacement)

    now = datetime.now(timezone.utc)
    review_payload: dict = {}
    if request.note:
        review_payload["note"] = request.note
    review_id = uuid4()
    replacement_ids: list[UUID] = []

    try:
        async with db.transaction():
            if request.action == "merge":
                merge_group = str(uuid4())
                for other in merge_targets:
                    rid = uuid4()
                    if other["id"] == mark_id:
                        review_id = rid
                    await db.execute(
                        _INSERT_REVIEW_SQL, rid, room_id, "merge", other["id"],
                        current_user.user_id, now,
                        {**review_payload, "merge_group": merge_group},
                    )
                replacement = replacement_requests[0]
                replacement_id = uuid4()
                subjects = [s.model_dump() for s in replacement.subjects]
                payload = dict(replacement.payload)
                payload["merged_ids"] = [str(t["id"]) for t in merge_targets]
                await db.execute(
                    _INSERT_RELATION_SQL, replacement_id, room_id, target["thread_id"],
                    replacement.relation, subjects, replacement.title, payload,
                    mark_id, review_id, current_user.user_id, now,
                    compute_dedup_key(replacement.relation, subjects),
                )
                replacement_ids = [replacement_id]
            else:
                await db.execute(
                    _INSERT_REVIEW_SQL, review_id, room_id, request.action, mark_id,
                    current_user.user_id, now, review_payload,
                )
                for replacement in replacement_requests:
                    replacement_id = uuid4()
                    subjects = [s.model_dump() for s in replacement.subjects]
                    await db.execute(
                        _INSERT_RELATION_SQL, replacement_id, room_id, target["thread_id"],
                        replacement.relation, subjects, replacement.title,
                        dict(replacement.payload), mark_id, review_id,
                        current_user.user_id, now,
                        compute_dedup_key(replacement.relation, subjects),
                    )
                    replacement_ids.append(replacement_id)

            event_payload = {
                "action": request.action,
                "target_mark_id": str(mark_id),
                "replacement_ids": [str(i) for i in replacement_ids],
                "actor_user_id": str(current_user.user_id),
            }
            if request.action == "merge":
                # A merge has several targets, not one — the event must name
                # them all or the non-primary sources vanish from the record.
                event_payload["merged_ids"] = [str(t["id"]) for t in merge_targets]
            await db.execute(
                _INSERT_EVENT_SQL, uuid4(), now, EventType.FIELD_MARK_REVIEWED.value,
                room_id, target["thread_id"], current_user.user_id,
                event_payload,
            )
    except asyncpg.UniqueViolationError:
        # A human's explicit correction is never silently no-op'd the way the
        # inference job's ON CONFLICT DO NOTHING silently skips a re-assertion
        # — the human asked for a write and the honest answer is that an
        # identical mark already exists.
        raise HTTPException(
            status_code=409,
            detail="an identical mark already exists (same relation and subjects)",
        )

    # Targeted single-mark builds, NOT the room-wide projection: that one is
    # capped at the newest 500 rows, so a review of a mark just past the cap
    # would commit and then be "missing" — a committed write must never be
    # reported as a failure (field_marks.build_single_mark's docstring).
    mark_out = await build_single_mark(db, room_id, mark_id)
    if mark_out is None:
        raise HTTPException(
            status_code=500, detail="review committed but mark is unreadable",
        )
    replacements_out = []
    for rid in replacement_ids:
        replacement_mark = await build_single_mark(db, room_id, rid)
        if replacement_mark is not None:
            replacements_out.append(replacement_mark)
    review_out = FieldReview(
        id=review_id, action=request.action, actor_user_id=current_user.user_id,
        note=request.note, created_at=now,
    )
    return FieldReviewResponse(
        review=review_out, replacements=replacements_out, mark=mark_out,
    )
