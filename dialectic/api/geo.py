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
from world_signals import (
    WorldSignal,
    WorldSignalExpired,
    WorldSignalMalformedId,
    WorldSignalNotFound,
    WorldSignalWrongRoom,
    world_signal_store,
)

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

_WORLD_OBSERVATIONS_LIST_SQL = """
SELECT wo.id, wo.scope_id, g.label AS scope_label, wo.provider, wo.signal_id,
       wo.layer, wo.kind, wo.label, wo.geometry, wo.provenance, wo.details,
       wo.observed_at, wo.retrieved_at, wo.first_seen_at, wo.last_seen_at,
       wo.seen_count
FROM world_observations wo
JOIN geo_scopes g ON g.id = wo.scope_id
WHERE wo.room_id = $1 AND wo.last_seen_at > now() - ($2::int * interval '1 hour')
ORDER BY wo.last_seen_at DESC
LIMIT $3
"""

_WORLD_OBSERVATIONS_COUNTS_SQL = """
SELECT wo.scope_id, g.label AS scope_label, wo.layer, count(*) AS n,
       count(*) FILTER (WHERE (wo.details->>'novel')::boolean) AS novel,
       max(wo.last_seen_at) AS newest_at
FROM world_observations wo
JOIN geo_scopes g ON g.id = wo.scope_id
WHERE wo.room_id = $1 AND wo.last_seen_at > now() - ($2::int * interval '1 hour')
GROUP BY wo.scope_id, g.label, wo.layer
ORDER BY newest_at DESC
"""

_OBSERVATIONS_CAP = 500
_OBSERVATIONS_HOURS_MIN = 1
_OBSERVATIONS_HOURS_MAX = 168

_PLACED_SIGNAL_SQL = """
SELECT id
FROM geo_scopes
WHERE room_id = $1
  AND subject->>'entity' = 'rooms'
  AND subject->>'id' = $1::text
  AND subject->>'field' = $2
  AND revision_action = 'place_signal'
ORDER BY created_at
LIMIT 2
"""


def _resolve_world_signal(room_id: UUID, signal_id: str) -> WorldSignal:
    try:
        return world_signal_store.resolve(room_id, signal_id)
    except WorldSignalMalformedId as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (WorldSignalNotFound, WorldSignalWrongRoom) as exc:
        raise HTTPException(status_code=404, detail="signal not found in this room") from exc
    except WorldSignalExpired as exc:
        raise HTTPException(status_code=409, detail="signal is expired") from exc


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


class WorldObservationOut(BaseModel):
    """One durable provider contact, exactly as read — geometry included,
    because this is the row a human explicitly asked to see (the read door
    the plan calls out), unlike room_record.py's ambient prompt section,
    which deliberately never renders a coordinate to the model."""

    id: str
    scope_id: str
    scope_label: str
    provider: str
    signal_id: str
    layer: str
    kind: str
    label: str
    geometry: dict
    provenance: dict
    details: dict
    observed_at: Optional[datetime] = None
    retrieved_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int


class WorldObservationCountOut(BaseModel):
    scope_id: str
    scope_label: str
    layer: str
    count: int
    # Fires only: cells world_watch scored NEW against the room's 30-day
    # baseline. An exact aggregate, unlike the 500-row `observations` list,
    # so a room whose aircraft churn fills the newest 500 still counts right.
    novel: int = 0
    newest_at: Optional[datetime] = None


class WorldObservationsResponse(BaseModel):
    observations: list[WorldObservationOut]
    counts: list[WorldObservationCountOut]


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


@router.get(
    "/rooms/{room_id}/world/observations", response_model=WorldObservationsResponse,
)
async def get_world_observations(
    room_id: UUID,
    hours: int = 24,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> WorldObservationsResponse:
    """Durable provider observations inside this room's confirmed geography
    (World Lens plan, Step 1/4) — the frontend's read of `world_observations`.
    Same auth as every other room-scoped geo route. `hours` is CLAMPED, never
    rejected, to [1, 168] — an out-of-range caller gets the nearest legal
    window rather than a 422. Rows capped at the 500 newest; counts are
    exact and unbounded (aggregates, not rows)."""
    await _authorize(room_id, token, current_user.user_id, db)
    bounded_hours = max(_OBSERVATIONS_HOURS_MIN, min(_OBSERVATIONS_HOURS_MAX, hours))
    rows = await db.fetch(
        _WORLD_OBSERVATIONS_LIST_SQL, room_id, bounded_hours, _OBSERVATIONS_CAP,
    )
    count_rows = await db.fetch(_WORLD_OBSERVATIONS_COUNTS_SQL, room_id, bounded_hours)
    return WorldObservationsResponse(
        observations=[
            WorldObservationOut(
                id=str(row["id"]),
                scope_id=f"geo_scope:{row['scope_id']}",
                scope_label=row["scope_label"],
                provider=row["provider"],
                signal_id=row["signal_id"],
                layer=row["layer"],
                kind=row["kind"],
                label=row["label"],
                geometry=row["geometry"],
                provenance=row["provenance"],
                details=row["details"],
                observed_at=row["observed_at"],
                retrieved_at=row["retrieved_at"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                seen_count=row["seen_count"],
            )
            for row in rows
        ],
        counts=[
            WorldObservationCountOut(
                scope_id=f"geo_scope:{row['scope_id']}",
                scope_label=row["scope_label"],
                layer=row["layer"],
                count=row["n"],
                novel=row.get("novel", 0) or 0,
                newest_at=row["newest_at"],
            )
            for row in count_rows
        ],
    )


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


@router.post(
    "/rooms/{room_id}/world-signals/{signal_id}/place",
    response_model=GeoScope,
    status_code=201,
)
async def place_world_signal(
    room_id: UUID,
    signal_id: str,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> GeoScope:
    """Copy one current server-held observation into durable GeoScope history.

    The request has no body: geometry, provenance, source condition, coverage,
    and observation clocks come only from the in-process owner. A transaction-
    scoped advisory lock gives a repeated/concurrent human tap one durable row
    and one event without adding a provider-specific uniqueness rule to the
    general ``geo_scopes`` table.
    """
    await _authorize(room_id, token, current_user.user_id, db)
    signal = _resolve_world_signal(room_id, signal_id)
    async with db.transaction():
        await db.fetchval(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"world-signal-place:{room_id}:{signal.id}",
        )
        # This is the placement linearization point. A provider replacement,
        # removal, or expiry while this request waited for the lock wins.
        signal = _resolve_world_signal(room_id, signal_id)
        now = datetime.now(timezone.utc)
        subject = {"entity": "rooms", "id": str(room_id), "field": signal.id}
        existing_rows = await db.fetch(_PLACED_SIGNAL_SQL, room_id, signal.id)
        if len(existing_rows) > 1:
            raise ValueError("world signal has more than one durable placement")
        if existing_rows:
            existing = await GeoScopeService(db).get(room_id, existing_rows[0]["id"])
            if existing is None:
                raise ValueError("world signal placement no longer resolves")
            return existing

        scope_id = await insert_scope(
            db,
            room_id=room_id,
            subject=subject,
            kind=signal.kind,
            geometry=signal.geometry,
            authority="source_reported",
            provenance=signal.provenance.model_dump(),
            label=signal.label,
            observed_at=signal.observed_at,
            retrieved_at=signal.retrieved_at,
            expires_at=signal.expires_at,
            source_state=signal.source_state,
            created_by=current_user.user_id,
            revision_action="place_signal",
            now=now,
        )
        scope = await GeoScopeService(db).get(room_id, scope_id)
        assert scope is not None
        await _record_event(
            db,
            now=now,
            event_type=EventType.GEO_SCOPE_CREATED.value,
            room_id=room_id,
            user_id=current_user.user_id,
            payload={"scope_id": str(scope_id), **_scope_payload(scope)},
        )
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
            if action == "ratify" and (
                target.supersedes_id is not None
                or target.revision_action not in ("place", "place_signal")
            ):
                raise HTTPException(
                    status_code=409,
                    detail="only an original accepted placement can be ratified",
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
