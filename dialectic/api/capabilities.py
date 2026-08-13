# api/capabilities.py — which doors this deployment actually has open.
#
# ARCHITECTURE: an unauthenticated, boolean-only projection of gates that are
# enforced elsewhere. It owns no policy. Every field here is answered by calling
# the predicate that does the enforcing, so the screen cannot advertise a door
# the server refuses.
#
# WHY it exists: the signed-out screen renders before any credential, so it had
# no way to ask whether registration was open. It offered a Create Account form,
# took three fields and a submit, and only then surfaced a 403. A closed door
# should be closed on sight, not after the user has done the work.
#
# TRADEOFF: importing `_signups_enabled` reaches for a private name in
# api.auth.routes, which is deliberate and is the whole point of the module. The
# alternative — re-reading SIGNUPS_ENABLED here — compiles, passes an obvious
# test, and is wrong the day the signup rule changes shape, because the UI and
# the route would then disagree with nobody noticing. A guard must not re-derive
# the rule it reports on. If that name is ever made public, import the public
# one; do not copy the logic.
#
# WHAT MUST NOT GO HERE: anything that is not a plain boolean about a door.
# This surface is reachable without credentials, so it can never carry
# configuration, identifiers, or secrets. tests/test_capabilities_api.py asserts
# every value is a bool precisely so a future field cannot smuggle one out.
#
# WHY it lives under /auth and not a tidier /meta: the SPA is served by nginx,
# which proxies exactly one hardcoded list of path prefixes to this backend
# (sites-available/dialectic, and vite.config.ts mirrors it for dev/preview).
# A path outside that list is answered by the SPA fallback with 200 + index.html
# — so the fetch would parse HTML as JSON, throw, and leave the screen on its
# "unknown means closed" default. That failure is INVISIBLE here, because closed
# is the correct answer on this deployment today; it would surface only on the
# day someone opens signups and the screen refuses to notice. Choosing an
# already-proxied prefix buys the same semantics with no production routing
# change. If this grows beyond auth doors, add the prefix to BOTH lists first.

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.auth.routes import _signups_enabled
from api.token_utils import extract_room_token

router = APIRouter(tags=["capabilities"])

_db_pool = None


def set_capabilities_db_pool(pool):
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


class Capabilities(BaseModel):
    """Doors, as booleans. No configuration, no identifiers, no secrets."""

    signups_enabled: bool


@router.get("/auth/capabilities", response_model=Capabilities)
async def get_capabilities() -> Capabilities:
    """What a caller may do here, answered before they have a credential."""
    return Capabilities(signups_enabled=_signups_enabled())


class ScheduledJob(BaseModel):
    """One background job, as the running scheduler holds it."""

    name: str
    enabled: bool
    interval_s: int
    daily_at: Optional[str] = None


class RoomCapabilities(BaseModel):
    """What this room can actually do, and what is actually running for it."""

    thesis_bound: bool
    auto_interjection: bool
    interjection_turn_threshold: int
    scheduler_running: bool
    jobs: list[ScheduledJob] = []


@router.get("/rooms/{room_id}/capabilities", response_model=RoomCapabilities)
async def get_room_capabilities(
    room_id: UUID,
    request: Request,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> RoomCapabilities:
    """What this room can do — read from the room and the running scheduler.

    WHY this is not a static help page: the help modal described a daily rhythm
    of jobs that are mostly OFF in this deployment (WIRE, NEWS_DIGEST,
    PREDICTION_WATCH and READING_ECHO all default off), and advertised a fixed
    number of live theses. A new user read a description of a system that was
    not running.

    The job list is read from `app.state.scheduler.jobs` — the SAME objects the
    scheduler loop iterates — and each job answers `enabled()` itself, at call
    time, from its own env var. A second roster here would satisfy every test
    that asks "is wire mentioned" while reporting the opposite of what runs.

    When no scheduler exists (SCHEDULER_ENABLED=0, or a failed pool) the honest
    answer is an empty list, never the roster it WOULD have registered.
    """
    room = await db.fetchrow(
        """SELECT linked_book_id, auto_interjection_enabled,
                  interjection_turn_threshold
           FROM rooms WHERE id = $1 AND token = $2""",
        room_id, token,
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

    scheduler = getattr(request.app.state, "scheduler", None)
    jobs = [
        ScheduledJob(
            name=job.name,
            enabled=job.enabled(),
            interval_s=job.interval_s,
            daily_at=job.daily_at,
        )
        for job in getattr(scheduler, "jobs", [])
    ]

    return RoomCapabilities(
        thesis_bound=room["linked_book_id"] is not None,
        auto_interjection=bool(room["auto_interjection_enabled"]),
        interjection_turn_threshold=int(room["interjection_turn_threshold"]),
        scheduler_running=scheduler is not None,
        jobs=jobs,
    )
