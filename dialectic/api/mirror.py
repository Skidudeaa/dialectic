# api/mirror.py — the Mirror: what the participant thinks of YOU.
#
# ARCHITECTURE: since February `llm/identity.py` has kept a private, versioned
# prose model of each human, per room, as a `user_model:<user_id>` memory with
# the full rewrite history in `memory_versions`. This module is three GETs onto
# those rows — no writes, no data of its own. Same shape as api/atlas.py:
# authorize from the JWT, project rows that already exist.
#
# WHAT IS ACTUALLY NEW, stated precisely because the first draft of this
# comment claimed nothing had ever read one back and that is FALSE:
# `GET /rooms/{room_id}/user-models/{user_id}` (api/main.py:1845) has served
# the caller's CURRENT model for one room since long before this. What did not
# exist is the history — the versions, the diff between any two, and the
# cross-room list — which is the whole of why this is worth reading: a single
# current paragraph is a fact about you, and 134 of them in sequence is a
# theory of you being revised.
#
# WHY THE FENCE IS IN THE QUERY, NOT A FILTER: `memories.owner_user_id` is NULL
# on every one of these rows — `llm/identity.py` writes them LLM-authored, so
# the KEY is the only thing that carries whose model it is. That makes a
# post-fetch filter the entire attack surface: one forgotten `if` and Amo reads
# Dan's psychological profile. So every statement below binds
# `key = 'user_model:' || <authenticated user id>` and no statement ever selects
# a row it must later discard. `room_id` arrives from the caller and is only
# ever ANDed with that key, so a guessed or hostile room id can widen nothing.
# The corollary is deliberate: a room where only the OTHER person has a model
# is indistinguishable from a room with no model at all, in the list, in the
# counts, and in the 404. Amo cannot learn that a profile of Dan exists.
#
# WHY /users/me/mirror AND NOT /mirror: the `users` prefix is already proxied
# by nginx and vite.config.ts (api/atlas.py's header records the same fact);
# a bare `/mirror` prefix would need an edit to both, in two shared files, for
# no gain. The path says the same thing the fence does.
#
# TRADEOFF: `/versions` returns each version's full prose, not just its stamp.
# The corpus is ~1.5 KB per version and at most ~55 versions per room, so one
# request lets the reader step back through the whole history without a
# round-trip per step — and stepping back is the entire point of the surface.

import difflib
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mirror"])

_db_pool = None


def set_mirror_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


def _key(user_id: UUID) -> str:
    """The one place the fence value is built. `llm/identity.py`'s
    `_user_model_key` writes exactly this string; if that ever changes, both
    ends must move together or the Mirror simply shows nothing — which is the
    safe direction for this particular seam to fail in."""
    return f"user_model:{user_id}"


class MirrorRoom(BaseModel):
    room_id: UUID
    room_name: Optional[str]
    version: int
    updated_at: str
    content: str


class MirrorVersion(BaseModel):
    version: int
    updated_at: str
    content: str


class MirrorDiff(BaseModel):
    room_id: UUID
    from_version: int
    to_version: int
    lines: list[str]


@router.get("/users/me/mirror", response_model=list[MirrorRoom])
async def get_mirror(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> list[MirrorRoom]:
    """Every room in which the participant holds a model of the CALLER, with
    the current version, when it was last rewritten, and the prose itself."""
    rows = await db.fetch(
        """SELECT m.room_id, r.name AS room_name, m.version, m.updated_at,
                  m.content
             FROM memories m
             JOIN rooms r ON r.id = m.room_id
            WHERE m.key = $1 AND m.scope = 'llm' AND m.status = 'active'
              AND EXISTS (SELECT 1 FROM room_memberships rm
                           WHERE rm.room_id = m.room_id AND rm.user_id = $2)
            ORDER BY m.updated_at DESC""",
        _key(current_user.user_id), current_user.user_id,
    )
    return [
        MirrorRoom(
            room_id=row["room_id"],
            room_name=row["room_name"],
            version=row["version"],
            updated_at=row["updated_at"].isoformat(),
            content=row["content"],
        )
        for row in rows
    ]


async def _versions(db, room_id: UUID, user_id: UUID) -> list[MirrorVersion]:
    """Every rewrite of the caller's own model in one room, newest first.

    One statement, joined rather than resolved in two steps: a memory_id
    fetched separately and then reused is a window in which the fence is a
    variable rather than a predicate.

    CURRENT MEMBERSHIP is required, matching the older single-room door at
    api/main.py:1845 (which checks the room token AND membership). The key
    already guarantees the model is the caller's OWN, so this is not about
    whose profile it is — it is that a model written FROM a room's
    conversation can quote what the other person said in it, and
    `deploy/remove_home_member.sql` exists. Without this, removal would close
    the room and leave its transcript readable through the profile derived
    from it. `status = 'active'` for the matching reason: an invalidated
    model must not stay readable at /versions after it has left the list.
    """
    rows = await db.fetch(
        """SELECT mv.version, mv.updated_at, mv.content
             FROM memory_versions mv
             JOIN memories m ON m.id = mv.memory_id
            WHERE m.room_id = $1 AND m.key = $2 AND m.scope = 'llm'
              AND m.status = 'active'
              AND EXISTS (SELECT 1 FROM room_memberships rm
                           WHERE rm.room_id = m.room_id AND rm.user_id = $3)
            ORDER BY mv.version DESC""",
        room_id, _key(user_id), user_id,
    )
    return [
        MirrorVersion(
            version=row["version"],
            updated_at=row["updated_at"].isoformat(),
            content=row["content"],
        )
        for row in rows
    ]


@router.get("/users/me/mirror/{room_id}/versions", response_model=list[MirrorVersion])
async def get_mirror_versions(
    room_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> list[MirrorVersion]:
    versions = await _versions(db, room_id, current_user.user_id)
    if not versions:
        # Deliberately the same answer whether the room does not exist, the
        # caller was never in it, or the participant models only the OTHER
        # person there. The 404 must not be an oracle.
        raise HTTPException(status_code=404, detail="No mirror for this room")
    return versions


@router.get("/users/me/mirror/{room_id}/diff", response_model=MirrorDiff)
async def get_mirror_diff(
    room_id: UUID,
    from_version: int = Query(..., alias="from", ge=1),
    to_version: int = Query(..., alias="to", ge=1),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> MirrorDiff:
    """What changed between two rewrites, as unified-diff lines.

    stdlib `difflib` on purpose — no dependency earns its keep for this.
    """
    by_version = {v.version: v for v in await _versions(db, room_id, current_user.user_id)}
    a, b = by_version.get(from_version), by_version.get(to_version)
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="No such version")
    lines = list(
        difflib.unified_diff(
            a.content.splitlines(),
            b.content.splitlines(),
            fromfile=f"v{from_version}",
            tofile=f"v{to_version}",
            lineterm="",
        )
    )
    return MirrorDiff(
        room_id=room_id,
        from_version=from_version,
        to_version=to_version,
        lines=lines,
    )
