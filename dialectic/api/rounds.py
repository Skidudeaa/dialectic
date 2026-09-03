# api/rounds.py — the Sunday Round's forecast door.
#
# ARCHITECTURE: two writes (forecast, bin) and one read (the round's state as
# THIS caller is allowed to see it). Forecasts are rows in
# commitment_confidence, never entries in message metadata — see
# schema.sql:249-259, which states the rule about reactions: "Rows rather than
# a JSONB blob on the message: concurrent reactions cannot clobber each other."
# Two people setting a number on the same card within one round trip is that
# race exactly.
#
# THE BLINDNESS RULE, and why it lives HERE: with two forecasters there is no
# crowd to hide in, so seeing the other number first is pure anchoring. A
# question stays blind until BOTH have forecast it. That is enforced in this
# READ — a client-side hide is not blindness, it is a number sitting in a
# response body waiting for anyone who opens devtools. Owner's ruling,
# 2026-08-20.
#
# THE LATE-REVISION RULE: the scorer credits a forecast only for days at or
# before min(close, resolved_at). A revision entered after close therefore
# cannot count — so this door REFUSES it (409) rather than storing it and
# returning 200. The desk's own confidence endpoint has this exact bug: it
# accepts a post-deadline append, broadcasts "updated confidence to N%", and
# the scorer silently discards it. Confirming a write nobody will ever score
# is worse than refusing it.

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from stakes.house import HOUSE, split_by_actor
from stakes.manager import CommitmentManager
from stakes.timeweighted import (
    IGNORANCE_REF_BRIER,
    brier_skill_score,
    peer_delta,
    time_weighted_brier,
    time_weighted_log,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rounds"])

_db_pool: Optional[asyncpg.Pool] = None


def set_rounds_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("rounds database pool is not initialized")
    return _db_pool


class ForecastRequest(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: Optional[str] = None
    # THE SECOND SLIDER: where you think the OTHER one will land. Optional,
    # because a round nobody finishes scores nobody — the question you must
    # answer is your own number, and this one is a bet on your friend.
    peer_forecast: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ResolveRequest(BaseModel):
    resolution: str = Field(pattern="^(correct|incorrect|voided)$")
    notes: Optional[str] = None


async def _verify(room_id: UUID, token: str, user_id: UUID, db) -> None:
    if not await db.fetchval(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2", room_id, token,
    ):
        raise HTTPException(status_code=401, detail="Invalid room token")
    if not await db.fetchval(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    ):
        raise HTTPException(status_code=403, detail="Not a member of this room")


async def _load_question(db, room_id: UUID, commitment_id: UUID) -> dict:
    row = await db.fetchrow(
        """SELECT * FROM commitments
           WHERE id = $1 AND room_id = $2 AND category = 'round'""",
        commitment_id, room_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found in this room")
    return dict(row)


@router.post("/rooms/{room_id}/rounds/{commitment_id}/forecast")
async def record_forecast(
    room_id: UUID,
    commitment_id: UUID,
    request: ForecastRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Record — or revise — my own probability on one round question."""
    async with pool.acquire() as db:
        await _verify(room_id, token, current_user.user_id, db)
        question = await _load_question(db, room_id, commitment_id)

        if question["status"] == "binned":
            raise HTTPException(
                status_code=409,
                detail="This question was binned. Binned questions are never scored.",
            )
        # Refuse loudly rather than storing something the scorer will discard.
        deadline = question["deadline"]
        if deadline is not None and datetime.now(timezone.utc) > deadline:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This question closed on "
                    f"{deadline.date().isoformat()}. A forecast entered after "
                    "close cannot be scored, so it is not recorded."
                ),
            )

        manager = CommitmentManager(db)
        await manager.record_confidence(
            commitment_id=commitment_id,
            user_id=current_user.user_id,
            confidence=request.confidence,
            reasoning=request.reasoning,
            peer_forecast=request.peer_forecast,
        )
        return await _round_state(db, room_id, question["source_message_id"],
                                  current_user.user_id)


@router.post("/rooms/{room_id}/rounds/{commitment_id}/bin")
async def bin_question(
    room_id: UUID,
    commitment_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Veto a badly-formed question. Either forecaster may; it is never scored.

    Deliberately not reversible by a second tap — un-binning a question people
    have stopped thinking about would silently re-arm a scoring obligation.
    """
    async with pool.acquire() as db:
        await _verify(room_id, token, current_user.user_id, db)
        question = await _load_question(db, room_id, commitment_id)
        await db.execute(
            "UPDATE commitments SET status = 'binned' WHERE id = $1", commitment_id,
        )
        return await _round_state(db, room_id, question["source_message_id"],
                                  current_user.user_id)


@router.post("/rooms/{room_id}/rounds/{commitment_id}/resolve")
async def resolve_question(
    room_id: UUID,
    commitment_id: UUID,
    request: ResolveRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Settle a round question. A human taps; nothing resolves itself.

    ARCHITECTURE: this is the ONLY thing standing between a closed question
    and a score. The close-watch job gathers evidence and posts it, but the
    verdict is a human's — the same law as everywhere else in this codebase,
    and the reason is that the first wrong auto-settlement would cost the
    ledger its standing permanently and there is no way to earn that back.

    Early resolution is allowed on purpose: an event can happen before its
    close date, and the scorer's leak-safe boundary already caps the window
    at min(close, resolved_at), so settling early shortens the window for
    everyone equally rather than advantaging whoever noticed first.

    `voided` is not a third outcome. It sets status='voided' and the scorer
    refuses it outright — inventing a 0.5 for a binary question is exactly
    the manufactured number this ledger exists to avoid.
    """
    async with pool.acquire() as db:
        await _verify(room_id, token, current_user.user_id, db)
        question = await _load_question(db, room_id, commitment_id)

        if question["status"] == "binned":
            raise HTTPException(
                status_code=409,
                detail="This question was binned. Binned questions are never scored.",
            )
        if question["status"] != "active":
            # Re-settling would rewrite resolved_at and silently move every
            # scoring window that hangs off it.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This question was already settled as "
                    f"{question['resolution'] or question['status']}."
                ),
            )

        manager = CommitmentManager(db)
        try:
            await manager.resolve(
                commitment_id=commitment_id,
                resolution=request.resolution,
                resolved_by_user_id=current_user.user_id,
                resolution_notes=request.notes,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return await _round_state(db, room_id, question["source_message_id"],
                                  current_user.user_id)


@router.get("/rooms/{room_id}/rounds/{message_id}")
async def read_round(
    room_id: UUID,
    message_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """The round as this caller may see it — see the blindness rule above."""
    async with pool.acquire() as db:
        await _verify(room_id, token, current_user.user_id, db)
        return await _round_state(db, room_id, message_id, current_user.user_id)


async def _round_state(db, room_id: UUID, message_id, viewer_id: UUID) -> dict:
    """Project one round card for one viewer, applying the blindness rule."""
    questions = await db.fetch(
        """SELECT id, claim, deadline, status, resolution, resolved_at,
                  created_at
           FROM commitments
           WHERE room_id = $1 AND source_message_id = $2 AND category = 'round'
           ORDER BY created_at ASC""",
        room_id, message_id,
    )
    # WHO the other forecaster is, independent of whether they have answered.
    # The second slider asks "where will Dan land?", and before reveal the
    # card has no other way to learn his name — the only other place it
    # appears is inside a forecast, which is the one thing that must stay
    # sealed. Membership is not a secret between two members of the same
    # room; a probability is. This carries the former and never the latter.
    peers = await db.fetch(
        """SELECT u.id, u.display_name
           FROM room_memberships rm JOIN users u ON u.id = rm.user_id
           WHERE rm.room_id = $1 AND rm.user_id <> $2
           ORDER BY rm.joined_at""",
        room_id, viewer_id,
    )
    peer_names = {str(p["id"]): p["display_name"] for p in peers}
    out = []
    for question in questions:
        history = await db.fetch(
            """SELECT user_id, confidence, peer_forecast, recorded_at, actor,
                      reasoning
               FROM commitment_confidence
               WHERE commitment_id = $1
               ORDER BY recorded_at ASC""",
            question["id"],
        )
        # THE THREE-WAY SPLIT, and it must happen before anything else.
        # `actor` is the only thing that separates the participant's own
        # forecast from a person's; splitting on `user_id != viewer_id` alone
        # would drop the house row into `others` and unseal one human's blind
        # number to the other the moment the machine posted its own. See
        # stakes/house.py for why this has exactly one definition.
        humans, house_rows = split_by_actor(history)
        mine = [h for h in humans if h["user_id"] == viewer_id]
        others = [h for h in humans if h["user_id"] != viewer_id]
        other_ids = {h["user_id"] for h in others}

        # BOTH HUMANS must have committed before either is revealed. `mine`
        # being empty is the case that matters: it is exactly when a peek
        # would anchor the number this viewer is about to write. The house is
        # sealed by the same predicate and for the same reason — a machine
        # number on the card before you have written yours is an anchor with
        # a tool loop behind it.
        revealed = bool(mine) and bool(other_ids)

        entry = {
            "commitment_id": str(question["id"]),
            "claim": question["claim"],
            "closes": question["deadline"].date().isoformat()
            if question["deadline"] else None,
            "status": question["status"],
            "resolution": question["resolution"],
            "my_forecast": mine[-1]["confidence"] if mine else None,
            # My guess at what THEY will say. Mine to see at any time — it is
            # my own number, and hiding it from me would only stop me
            # revising it.
            "my_peer_forecast": mine[-1]["peer_forecast"] if mine else None,
            "my_revisions": len(mine),
            "revealed": revealed,
            "waiting_on_other": bool(mine) and not other_ids,
            "house_committed": bool(house_rows),
        }
        if revealed:
            entry["others"] = [
                {
                    "user_id": str(uid),
                    "forecast": [h for h in others if h["user_id"] == uid][-1][
                        "confidence"
                    ],
                    "revisions": len([h for h in others if h["user_id"] == uid]),
                }
                for uid in other_ids
            ]
            # THE MIRROR. How well did I read them? Signed, so it says which
            # way I was wrong — under- or over-estimating them is the part
            # that accumulates into a habit worth naming.
            if entry["my_peer_forecast"] is not None and entry["others"]:
                entry["peer_read_error"] = round(
                    entry["others"][0]["forecast"] - entry["my_peer_forecast"], 4,
                )
            if house_rows:
                entry["house"] = {
                    "forecast": house_rows[-1]["confidence"],
                    "revisions": len(house_rows),
                    "because": house_rows[-1]["reasoning"],
                }
        else:
            # Not merely hidden from the UI — absent from the response.
            entry["others_committed"] = len(other_ids)

        if question["resolution"] in ("correct", "incorrect"):
            entry["scores"] = _score_question(question, humans, house_rows)
        out.append(entry)
    return {
        "message_id": str(message_id),
        "questions": out,
        "peers": [
            {"user_id": uid, "display_name": name}
            for uid, name in peer_names.items()
        ],
    }


def _score_question(question, humans, house_rows=()) -> list[dict]:
    """Per-forecaster time-weighted Brier, coverage, and the head-to-head.

    WHY `opened` is the question's own creation and NOT the first forecast:
    the window is when the question was ASKABLE. Starting it at
    min(recorded_at) meant a forecaster who opened the card late was scored
    only across their own shorter window — and a shorter window sits nearer
    the outcome, so it is EASIER. Arriving late read as skill. Nothing has
    ever resolved through this path, so this is a fix before first use rather
    than a rescoring; changing it after the first settlement would have left
    two scoring eras in one table with nothing to tell them apart.

    `coverage` is what makes the absence honest: it is reported beside the
    Brier rather than folded into it, so a 0.09 across 30% of the question's
    life cannot be mistaken for a 0.09 across all of it.
    """
    opened = question["created_at"]
    scores = []
    daily_by_actor: dict[str, dict] = {}

    def _one(key: str, rows, label: dict) -> None:
        history = [
            {"recorded_at": r["recorded_at"], "confidence": r["confidence"]}
            for r in rows
        ]
        scored = time_weighted_brier(
            history,
            opened=opened,
            close=question["deadline"],
            resolved_at=question["resolved_at"],
            resolution=question["resolution"],
        )
        if scored is None:
            return
        logged = time_weighted_log(
            history,
            opened=opened,
            close=question["deadline"],
            resolved_at=question["resolved_at"],
            resolution=question["resolution"],
        )
        if logged:
            daily_by_actor[key] = logged["daily"]
        entry = {
            **label,
            **{k: v for k, v in scored.items()},
            "bss": brier_skill_score(scored["brier"], IGNORANCE_REF_BRIER),
            "log_score": logged["log_score"] if logged else None,
        }
        scores.append((key, entry))

    for user_id in {h["user_id"] for h in humans}:
        _one(
            str(user_id),
            [h for h in humans if h["user_id"] == user_id],
            {"user_id": str(user_id), "actor": "human"},
        )
    if house_rows:
        _one(HOUSE, list(house_rows), {"user_id": None, "actor": HOUSE})

    # The duel. Antisymmetric by construction, so it can only ever say that
    # one of them took the other's points — never that both are winning.
    peers = peer_delta(daily_by_actor)
    for key, entry in scores:
        entry.update(peers.get(key, {"peer": None, "contested_days": 0}))
    return [entry for _, entry in scores]


@router.get("/rounds/moves")
async def round_moves(
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Open round questions across every room the caller belongs to, with
    whether the caller has forecast and which peers have.

    WHY: Home should open on "Dan moved on Brent. Your move." (2026-09-02).
    Blindness rule as in _round_state: this carries names, never numbers —
    that a peer has moved is membership-grade information; where they landed
    stays sealed until both have committed. The house never appears here.
    """
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT c.id, c.room_id, r.name AS room_name, c.thread_id,
                      c.source_message_id, c.claim, c.deadline,
                      EXISTS (SELECT 1 FROM commitment_confidence cc
                               WHERE cc.commitment_id = c.id AND cc.user_id = $1
                                 AND cc.actor = 'human') AS mine,
                      COALESCE((SELECT array_agg(DISTINCT u.display_name)
                                  FROM commitment_confidence cc
                                  JOIN users u ON u.id = cc.user_id
                                 WHERE cc.commitment_id = c.id AND cc.user_id <> $1
                                   AND cc.actor = 'human'), ARRAY[]::text[]) AS peers_moved
               FROM commitments c
               JOIN rooms r ON r.id = c.room_id
               JOIN room_memberships rm ON rm.room_id = c.room_id AND rm.user_id = $1
               WHERE c.category = 'round' AND c.status = 'active'
                 AND c.deadline > now()
               ORDER BY c.deadline ASC
               LIMIT 50""",
            current_user.user_id,
        )
    moves = [
        {
            "commitment_id": str(r["id"]),
            "room_id": str(r["room_id"]),
            "room_name": r["room_name"],
            "thread_id": str(r["thread_id"]) if r["thread_id"] else None,
            "message_id": str(r["source_message_id"]) if r["source_message_id"] else None,
            "claim": r["claim"],
            "closes": r["deadline"].date().isoformat() if r["deadline"] else None,
            "mine": bool(r["mine"]),
            "peers_moved": list(r["peers_moved"] or []),
        }
        for r in rows
    ]
    # Your move first: a peer has committed and you have not.
    moves.sort(key=lambda m: (m["mine"], not m["peers_moved"], m["closes"] or ""))
    return {"moves": moves, "your_move": sum(1 for m in moves if not m["mine"])}
