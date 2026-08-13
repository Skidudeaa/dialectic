# api/workspace.py — the read-only workspace-object projection for one room.
#
# ARCHITECTURE: this endpoint owns no data. It authorizes, then hands the
# request to workspace_objects.py, which projects rows that already exist
# (design v2 §8.1). There is deliberately no POST, PATCH or DELETE here: an
# object's write path stays with the entity that owns it, and a surface that
# wants to act on a projection calls that entity's own endpoint. `read-only`
# is a property of the router, not a promise in a docstring.
#
# WHY the same two credentials as every other room endpoint: a projection is
# exactly as sensitive as the rows it projects, and a second, looser door into
# the same content would be the whole point of the fence undone.

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from workspace_objects import (
    WORKSPACE_OBJECT_KINDS,
    WorkspaceObjectProjection,
    build_projection,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace"])

_db_pool = None


def set_workspace_db_pool(pool):
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


@router.get(
    "/rooms/{room_id}/workspace/objects",
    response_model=WorkspaceObjectProjection,
)
async def get_workspace_objects(
    room_id: UUID,
    kind: Optional[str] = Query(
        None, description="Restrict to one workspace-object kind."
    ),
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Everything this room holds, in one shape. Projects; never writes."""
    room = await db.fetchrow(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2", room_id, token,
    )
    if not room:
        raise HTTPException(status_code=401, detail="Invalid room token")
    member = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, current_user.user_id,
    )
    if not member:
        raise HTTPException(
            status_code=403, detail="User is not a member of this room",
        )
    if kind is not None and kind not in WORKSPACE_OBJECT_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown kind: {kind}")

    projection = await build_projection(db, room_id, current_user.user_id)
    if kind is not None:
        projection = projection.model_copy(update={
            "objects": [o for o in projection.objects if o.kind == kind],
        })
    return projection
