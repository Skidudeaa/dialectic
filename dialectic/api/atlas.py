# api/atlas.py — Atlas: the caller's own cross-room map, read-only.
#
# ARCHITECTURE: this endpoint owns no data, same as api/workspace.py. It
# authorizes from the JWT alone, then hands off to atlas_objects.py, which
# projects rows that already exist. There is no POST, PATCH or DELETE here —
# Atlas is navigation, not a second door onto anything a human can act on.
#
# WHY JWT ONLY, NO ROOM TOKEN: Atlas is cross-room by construction (§5.4) — a
# room token names ONE room, and Atlas's whole point is showing every room the
# caller belongs to in one projection. The fence is `atlas_objects.py`'s own
# eligible-room array, built from the caller's identity alone. This mirrors
# `GET /users/me/home/activity` (api/home.py) exactly, which authorizes the
# same way for the same reason — a shared cross-room surface has no single
# room whose token could gate it.
#
# WHY `/users/me/atlas` NEEDS NO NGINX OR vite.config.ts EDIT: the `users`
# prefix is already proxied (dialectic/CLAUDE.md §6.4's hardcoded prefix
# list), the same fact that let `/users/me/home/activity` ship without one.

import logging

from fastapi import APIRouter, Depends, Query

from api.auth.dependencies import AuthenticatedUser, get_current_user
from atlas_objects import AtlasProjection, AtlasService, AtlasSignalProjection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["atlas"])

_db_pool = None


def set_atlas_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


@router.get(
    "/users/me/atlas",
    response_model=AtlasSignalProjection | AtlasProjection,
)
async def get_atlas(
    include_signals: bool = Query(False, alias="signals"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> AtlasProjection | AtlasSignalProjection:
    """The caller's own cross-room map: rooms, branches, theses, readings,
    briefs, commitments and unresolved work, plus the real-provenance edges
    between them. Fenced by the caller's OWN memberships (§5.4) — not the
    all-members intersection home_activity.py uses for the shared House.
    Projects; never writes.
    """
    return await AtlasService(db).build(
        current_user.user_id, include_signals=include_signals,
    )
