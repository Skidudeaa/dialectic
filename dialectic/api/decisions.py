# api/decisions.py — why a machine message happened, not what it says.
#
# ARCHITECTURE: since the interjection engine's first commit, every decision
# to speak (or stay silent) has been recorded in `llm_decisions` — reason,
# confidence, mode, the inputs that fed the decision — and NOTHING has ever
# read it back for a human to see. Owner's own words: "the user needs to be
# able to see EVERYWHERE what the fuck is going on." This is that read.
#
# WHY BATCHED, NOT PER-MESSAGE: a thread can carry dozens of machine
# messages, and MessageBubble renders once per message. A per-message
# endpoint would be dozens of round trips on every thread open. This takes a
# thread and returns every decision in it, keyed by the message id it
# produced, in ONE query — the frontend fetches once per thread load
# (frontend/app/src/hooks/useMessageDecisions.ts shares that one fetch
# across every bubble in the thread).
#
# WHY THE FENCE IS THE SAME SHAPE AS api/capabilities.py::get_room_capabilities:
# room token proves the caller holds the room's invite capability, membership
# proves they are actually IN it — the same two checks, in the same order, for
# the same reason. `llm_decisions` additionally carries its OWN `room_id`
# column, so the SELECT fences by `room_id = $1 AND thread_id = $2` directly
# (mirror.py's "the fence is in the query, not a filter" — a foreign or
# nonexistent thread_id can only ever match rows that ALSO carry the caller's
# own, already-authorized room_id, so it simply returns empty rather than
# needing a separate thread-ownership lookup).
#
# WHY NO 404 ON EMPTY: unlike api/mirror.py (where an empty answer is
# deliberately indistinguishable from "not found", for privacy), an empty
# decisions map here is the ordinary case — most threads have long stretches
# where nothing the LLM said was logged (llm_annotator never logs a decision
# at all; scheduled-job posts don't go through the interjection engine; older
# messages predate a logging fix). Empty is not an error, so it is 200 + {}.
#
# WHAT THIS RETURNS, AND WHY NOT MORE: reason, confidence, mode, whether the
# provoker was used, and the three raw inputs that make a reason legible
# (human_turn_count, semantic_novelty, unsurfaced_memory_count). Deliberately
# NOT `tool_calls` or `speaker_balance` (also on this table): those are raw
# internal traces, not what a reader needs to understand why a turn happened,
# and — independent of that judgment — nothing in this codebase has ever read
# either column back through Python (grep-verified), so returning them here
# would be the first, accidental caller of the double-encode tolerance
# `llm.self_model.parse_decision_jsonb` exists for for. If a future version
# of this route needs them, decode through that helper — never trust the
# column's declared type; roughly 192 legacy rows are permanently JSON
# strings where an array/object belongs (see that function's docstring).
#
# HOW THIS COMPOSES WITH messages.metadata.source: a DIFFERENT, ALREADY-
# PRESENT provenance channel — `source` says which scheduled job WROTE this
# message's content (reading_echo, night_shift, trading_curator, deep_dive);
# a decision row says WHY the interjection engine gave a turn to a message at
# all. Verified against every writer in llm/ (grep, not assumption): the two
# channels are DISJOINT today — nothing that stamps `metadata.source` also
# calls `self_model.log_decision` (those paths INSERT the message directly),
# and nothing that goes through the interjection engine / force_response
# stamps `metadata.source`. So a message has at most one of the two, never
# both, and this endpoint does not need to arbitrate — it simply returns
# whatever `llm_decisions` rows exist for the thread. The frontend
# (MessageBubble.tsx) is where the two are read side by side; ITS docstring
# states the precedence for the day they stop being disjoint (metadata.source
# wins, being the more specific claim — "this exact job wrote this exact
# content" — and the decision reason is never hidden, only secondary).

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["decisions"])

_db_pool = None


def set_decisions_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


class DecisionExplain(BaseModel):
    """Why the interjection engine gave ONE message a turn.

    `mode` and `use_provoker` are two views of the same underlying flag —
    at every current call site (llm/orchestrator.py) `mode == "provoker"`
    if and only if `use_provoker` was true. Returned as two fields anyway
    rather than making the client re-derive one from the other: that
    pairing is an observed property of today's code, not a contract this
    response promises to keep.

    Every field past `reason` is Optional because it is genuinely ABSENT on
    some rows, not merely zero: a forced turn (wire, silence follow-up,
    protocol) never ran the heuristic rungs, so it has no turn count, no
    novelty score, no unsurfaced-memory count to report. NULL says that;
    inventing 0 would read as "measured, and low".
    """

    reason: str
    confidence: Optional[float] = None
    mode: Optional[str] = None
    use_provoker: bool = False
    human_turn_count: Optional[int] = None
    semantic_novelty: Optional[float] = None
    unsurfaced_memory_count: Optional[int] = None


class ThreadDecisionsResponse(BaseModel):
    """Keyed by the message id the decision produced (`response_message_id`
    — always a real, resolvable row; a silence never appears here because it
    produced no message)."""

    decisions: dict[str, DecisionExplain]


@router.get(
    "/rooms/{room_id}/threads/{thread_id}/decisions",
    response_model=ThreadDecisionsResponse,
)
async def get_thread_decisions(
    room_id: UUID,
    thread_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> ThreadDecisionsResponse:
    """Every logged decision in one thread, keyed by the message it produced.

    Fenced exactly like GET /rooms/{room_id}/capabilities: a valid room
    token proves the invite capability, membership proves the caller is
    actually in the room. Both are required before the decisions query runs.
    """
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

    rows = await db.fetch(
        """SELECT response_message_id, reason, confidence, mode, use_provoker,
                  human_turn_count, semantic_novelty, unsurfaced_memory_count
             FROM llm_decisions
            WHERE room_id = $1 AND thread_id = $2
              AND response_message_id IS NOT NULL
            ORDER BY decided_at""",
        room_id, thread_id,
    )
    decisions = {
        str(row["response_message_id"]): DecisionExplain(
            reason=row["reason"],
            confidence=row["confidence"],
            mode=row["mode"],
            use_provoker=bool(row["use_provoker"]),
            human_turn_count=row["human_turn_count"],
            semantic_novelty=row["semantic_novelty"],
            unsurfaced_memory_count=row["unsurfaced_memory_count"],
        )
        for row in rows
    }
    return ThreadDecisionsResponse(decisions=decisions)
