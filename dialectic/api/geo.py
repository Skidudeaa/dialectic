# api/geo.py — the World Lens write door: a human places, confirms, rejects.
#
# ARCHITECTURE: GET is a thin wrapper over geo_scopes.GeoScopeService, the
# same shape as api/field.py's GET. The three POSTs are this router's reason
# to exist: a person attaches geometry to a row (human_confirmed, stamped
# with the caller in the same insert), confirms the participant's proposal
# (a NEW human_confirmed row naming the proposal in supersedes_id), or
# rejects it (a NEW human_confirmed row whose source_state is
# confirmed_empty). Nothing here UPDATEs or DELETEs a geo_scopes row.
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
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from geo_scopes import (
    GEO_KINDS,
    GeoProjection,
    GeoScope,
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
                created_by=current_user.user_id, now=now,
            )
            await db.execute(
                _INSERT_EVENT_SQL, uuid4(), now, EventType.GEO_SCOPE_CREATED.value,
                room_id, current_user.user_id,
                {"scope_id": str(scope_id), "kind": request.kind,
                 "subject": subject, "authority": "human_confirmed"},
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    scope = await GeoScopeService(db).get(room_id, scope_id)
    assert scope is not None
    return scope


async def _review(room_id: UUID, scope_id: UUID, action: str,
                  current_user: AuthenticatedUser, db) -> GeoScope:
    """confirm | reject a machine_proposed scope, append-only.

    Both actions INSERT a human_confirmed row that names the proposal in
    supersedes_id, so the proposal stops being live by derivation. Confirm
    copies the geometry forward; reject copies it too but with
    source_state='confirmed_empty' — the geometry is kept as the record of
    what was rejected, and the live predicate hides it.
    """
    service = GeoScopeService(db)
    target = await service.get(room_id, scope_id)
    if target is None:
        raise HTTPException(status_code=404, detail="scope not found in this room")
    if target.authority != "machine_proposed":
        raise HTTPException(
            status_code=409, detail="only a machine_proposed scope can be reviewed",
        )
    if not await service.is_live(scope_id):
        raise HTTPException(status_code=409, detail="scope is no longer live")
    now = datetime.now(timezone.utc)
    provenance = {**target.provenance.model_dump(), "acquisition": "human"}
    async with db.transaction():
        new_id = await insert_scope(
            db, room_id=room_id, subject=target.subject.model_dump(),
            kind=target.kind, geometry=target.geometry, label=target.label,
            authority="human_confirmed", provenance=provenance,
            observed_at=target.observed_at,
            source_state="ok" if action == "confirm" else "confirmed_empty",
            confirmed_by=current_user.user_id, supersedes_id=scope_id,
            created_by=current_user.user_id, now=now,
        )
        await db.execute(
            _INSERT_EVENT_SQL, uuid4(), now, EventType.GEO_SCOPE_REVIEWED.value,
            room_id, current_user.user_id,
            {"scope_id": str(scope_id), "action": action,
             "replacement_id": str(new_id)},
        )
    scope = await service.get(room_id, new_id)
    assert scope is not None
    return scope


@router.post("/rooms/{room_id}/geo/{scope_id}/confirm", response_model=GeoScope, status_code=201)
async def confirm_geo_scope(
    room_id: UUID, scope_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    return await _review(room_id, scope_id, "confirm", current_user, db)


@router.post("/rooms/{room_id}/geo/{scope_id}/reject", response_model=GeoScope, status_code=201)
async def reject_geo_scope(
    room_id: UUID, scope_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    await _authorize(room_id, token, current_user.user_id, db)
    return await _review(room_id, scope_id, "reject", current_user, db)
