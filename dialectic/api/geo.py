# api/geo.py — the World Lens write door: append-only human authority.
#
# ARCHITECTURE: GET projects live scopes or one complete review lineage.
# Every POST appends a row and a full-fidelity event atomically: place,
# confirm, reject, ratify, redraw, or supersede. Provider source condition is
# copied forward unchanged; revision_action owns the human decision axis.
# Nothing here UPDATEs or DELETEs a geo_scopes row.
#
# WHY the same two credentials as every other room endpoint: `_authorize` is
# api/field.py's verbatim — a coordinate is exactly as sensitive as the room
# it reasons about.
#
# WHY there is no machine write route here: the participant proposes through
# an LLM tool (llm/world.py, Phase 2), never through HTTP, so nothing a
# browser can reach mints machine_proposed rows. This router is human-only.

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from geo_scopes import (
    GEO_KINDS,
    GeoProjection,
    GeoScope,
    GeoScopeReview,
    GeoScopeService,
    GeoSubjectRef,
    insert_scope,
    resolve_subject_in_room,
    validate_geometry,
)
from models import EventType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["geo"])

_db_pool = None


def set_geo_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


async def _authorize(room_id: UUID, token: str, user_id: UUID, db) -> None:
    """Both credentials, exactly as every other room endpoint requires them
    (copied from api/field.py:63)."""
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


_INSERT_EVENT_SQL = """
INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
VALUES ($1, $2, $3, $4, NULL, $5, $6)
"""


class GeoProvenanceRequest(BaseModel):
    """What a human may say about where geometry came from. `acquisition`
    is not a field: a row written through this door was acquired by a human,
    whatever provider's shape they chose (a Natural Earth ring, a hand-drawn
    lane). The server stamps it."""
    provider: str = "human"
    source_id: Optional[str] = None
    url: Optional[str] = None
    credit: str = ""


class GeoScopeCreateRequest(BaseModel):
    subject: GeoSubjectRef
    kind: str
    geometry: dict
    label: str = ""
    provenance: GeoProvenanceRequest = Field(default_factory=GeoProvenanceRequest)
    observed_at: Optional[datetime] = None


class GeoReviewNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = None


class GeoRedrawRequest(BaseModel):
    """A redraw changes only the human replacement shape and its note.
    Subject, kind, provenance, and source condition stay server-owned."""
    model_config = ConfigDict(extra="forbid")

    label: str
    geometry: dict
    note: Optional[str] = None


def _timestamp(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _scope_payload(scope: GeoScope) -> dict[str, Any]:
    return {
        "subject": scope.subject.model_dump(),
        "kind": scope.kind,
        "geometry": scope.geometry,
        "label": scope.label,
        "authority": scope.authority,
        "provenance": scope.provenance.model_dump(),
        "source_state": scope.source_state,
        "observed_at": _timestamp(scope.observed_at),
        "retrieved_at": _timestamp(scope.retrieved_at),
        "expires_at": _timestamp(scope.expires_at),
        "revision_action": scope.revision_action,
        "review_note": scope.review_note,
    }


async def _record_event(
    db: Any, *, now: datetime, event_type: str, room_id: UUID, user_id: UUID,
    payload: dict[str, Any],
) -> None:
    await db.execute(
        _INSERT_EVENT_SQL, uuid4(), now, event_type, room_id, user_id, payload,
    )


@router.get("/rooms/{room_id}/geo", response_model=GeoProjection)
async def get_geo(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoProjection:
    """Every live scope in the room. Projects; never writes."""
    await _authorize(room_id, token, current_user.user_id, db)
    return await GeoScopeService(db).build(room_id)


@router.post("/rooms/{room_id}/geo", response_model=GeoScope, status_code=201)
async def create_geo_scope(
    room_id: UUID,
    request: GeoScopeCreateRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    """A person attaches geometry to a row this room owns.

    The subject is resolved in SQL (a document is not a trust boundary);
    the geometry is validated by the owning module; the row is
    human_confirmed with the caller as confirmed_by in the same insert.
    """
    await _authorize(room_id, token, current_user.user_id, db)
    if request.kind not in GEO_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown kind: {request.kind}")
    subject = request.subject.model_dump()
    if not await resolve_subject_in_room(db, room_id, subject):
        raise HTTPException(
            status_code=422, detail="subject does not resolve to a row in this room",
        )
    provenance = {**request.provenance.model_dump(), "acquisition": "human"}
    # Geometry is refused BEFORE any SQL — the owning module's validator is
    # the door, the DB CHECKs are the backstop.
    try:
        validate_geometry(request.kind, request.geometry)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    now = datetime.now(timezone.utc)
    try:
        async with db.transaction():
            scope_id = await insert_scope(
                db, room_id=room_id, subject=subject, kind=request.kind,
                geometry=request.geometry, label=request.label,
                authority="human_confirmed", provenance=provenance,
                observed_at=request.observed_at,
                confirmed_by=current_user.user_id,
                created_by=current_user.user_id, revision_action="place", now=now,
            )
            scope = await GeoScopeService(db).get(room_id, scope_id)
            assert scope is not None
            await _record_event(
                db, now=now, event_type=EventType.GEO_SCOPE_CREATED.value,
                room_id=room_id, user_id=current_user.user_id,
                payload={"scope_id": str(scope_id), **_scope_payload(scope)},
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    scope = await GeoScopeService(db).get(room_id, scope_id)
    assert scope is not None
    return scope


async def _review(
    room_id: UUID, scope_id: UUID, action: str,
    current_user: AuthenticatedUser, db, *, review_note: Optional[str] = None,
    replacement_label: Optional[str] = None,
    replacement_geometry: Optional[dict] = None,
) -> GeoScope:
    """Append one locked successor and its complete event in one transaction."""
    if action not in ("confirm", "reject", "redraw", "supersede", "ratify"):
        raise ValueError(f"unknown geo review action: {action}")
    service = GeoScopeService(db)
    now = datetime.now(timezone.utc)
    try:
        async with db.transaction():
            target = await service.get_for_update(room_id, scope_id)
            if target is None:
                raise HTTPException(status_code=404, detail="scope not found in this room")
            if not await service.is_live(scope_id):
                raise HTTPException(status_code=409, detail="scope is no longer live")
            if action in ("confirm", "reject") and target.authority != "machine_proposed":
                raise HTTPException(
                    status_code=409,
                    detail="only a machine_proposed scope can be confirmed or rejected",
                )
            if action == "ratify" and target.review_state != "accepted":
                raise HTTPException(
                    status_code=409,
                    detail="only an accepted scope can be ratified",
                )
            if action in ("redraw", "supersede") and target.review_state != "accepted":
                raise HTTPException(
                    status_code=409, detail="only an accepted scope can be revised",
                )
            if action == "redraw" and replacement_geometry is None:
                raise ValueError("redraw geometry is required")

            new_id = await insert_scope(
                db, room_id=room_id, subject=target.subject.model_dump(),
                kind=target.kind,
                geometry=(replacement_geometry if action == "redraw" else target.geometry),
                label=(replacement_label if action == "redraw" else target.label) or "",
                authority="human_confirmed",
                provenance=target.provenance.model_dump(),
                observed_at=target.observed_at,
                retrieved_at=target.retrieved_at,
                expires_at=None if action == "confirm" else target.expires_at,
                source_state=target.source_state,
                confirmed_by=current_user.user_id,
                supersedes_id=scope_id,
                revision_action=action,
                review_note=review_note,
                created_by=current_user.user_id,
                now=now,
            )
            review = await service.review(room_id, new_id)
            assert review is not None
            successor = review.current
            await _record_event(
                db, now=now, event_type=EventType.GEO_SCOPE_REVIEWED.value,
                room_id=room_id, user_id=current_user.user_id,
                payload={
                    "scope_id": str(scope_id),
                    "action": action,
                    "replacement_id": str(new_id),
                    "root_scope_id": review.root_id.split(":", 1)[1],
                    **_scope_payload(successor),
                },
            )
    except asyncpg.UniqueViolationError as exc:
        if exc.constraint_name != "idx_geo_scopes_one_successor":
            raise
        raise HTTPException(status_code=409, detail="scope already has a successor") from exc
    scope = await service.get(room_id, new_id)
    assert scope is not None
    return scope


@router.post("/rooms/{room_id}/geo/{scope_id}/confirm", response_model=GeoScope, status_code=201)
async def confirm_geo_scope(
    room_id: UUID, scope_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    request: Optional[GeoReviewNoteRequest] = None,
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    return await _review(
        room_id, scope_id, "confirm", current_user, db,
        review_note=request.note if request else None,
    )


@router.post("/rooms/{room_id}/geo/{scope_id}/reject", response_model=GeoScope, status_code=201)
async def reject_geo_scope(
    room_id: UUID, scope_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    request: Optional[GeoReviewNoteRequest] = None,
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    return await _review(
        room_id, scope_id, "reject", current_user, db,
        review_note=request.note if request else None,
    )


@router.get("/rooms/{room_id}/geo/{scope_id}/review", response_model=GeoScopeReview)
async def get_geo_review(
    room_id: UUID, scope_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScopeReview:
    await _authorize(room_id, token, current_user.user_id, db)
    review = await GeoScopeService(db).review(room_id, scope_id)
    if review is None:
        raise HTTPException(status_code=404, detail="scope not found in this room")
    return review


@router.post("/rooms/{room_id}/geo/{scope_id}/ratify", response_model=GeoScope, status_code=201)
async def ratify_geo_scope(
    room_id: UUID, scope_id: UUID,
    request: Optional[GeoReviewNoteRequest] = None,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    return await _review(
        room_id, scope_id, "ratify", current_user, db,
        review_note=request.note if request else None,
    )


@router.post("/rooms/{room_id}/geo/{scope_id}/redraw", response_model=GeoScope, status_code=201)
async def redraw_geo_scope(
    room_id: UUID, scope_id: UUID, request: GeoRedrawRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    try:
        return await _review(
            room_id, scope_id, "redraw", current_user, db,
            review_note=request.note, replacement_label=request.label,
            replacement_geometry=request.geometry,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rooms/{room_id}/geo/{scope_id}/supersede", response_model=GeoScope, status_code=201)
async def supersede_geo_scope(
    room_id: UUID, scope_id: UUID,
    request: Optional[GeoReviewNoteRequest] = None,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    return await _review(
        room_id, scope_id, "supersede", current_user, db,
        review_note=request.note if request else None,
    )
