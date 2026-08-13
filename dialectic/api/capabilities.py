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

from fastapi import APIRouter
from pydantic import BaseModel

from api.auth.routes import _signups_enabled

router = APIRouter(tags=["capabilities"])


class Capabilities(BaseModel):
    """Doors, as booleans. No configuration, no identifiers, no secrets."""

    signups_enabled: bool


@router.get("/auth/capabilities", response_model=Capabilities)
async def get_capabilities() -> Capabilities:
    """What a caller may do here, answered before they have a credential."""
    return Capabilities(signups_enabled=_signups_enabled())
