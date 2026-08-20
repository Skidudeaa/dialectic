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
from stakes.manager import CommitmentManager
from stakes.timeweighted import IGNORANCE_REF_BRIER, brier_skill_score, time_weighted_brier

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
        """SELECT id, claim, deadline, status, resolution, resolved_at
           FROM commitments
           WHERE room_id = $1 AND source_message_id = $2 AND category = 'round'
           ORDER BY created_at ASC""",
        room_id, message_id,
    )
    out = []
    for question in questions:
        history = await db.fetch(
            """SELECT user_id, confidence, recorded_at
               FROM commitment_confidence
               WHERE commitment_id = $1
               ORDER BY recorded_at ASC""",
            question["id"],
        )
        mine = [h for h in history if h["user_id"] == viewer_id]
        others = [h for h in history if h["user_id"] != viewer_id]
        other_ids = {h["user_id"] for h in others}

        # BOTH must have committed before either is revealed. `mine` being
        # empty is the case that matters: it is exactly when a peek would
        # anchor the number this viewer is about to write.
        revealed = bool(mine) and bool(other_ids)

        entry = {
            "commitment_id": str(question["id"]),
            "claim": question["claim"],
            "closes": question["deadline"].date().isoformat()
            if question["deadline"] else None,
            "status": question["status"],
            "resolution": question["resolution"],
            "my_forecast": mine[-1]["confidence"] if mine else None,
            "my_revisions": len(mine),
            "revealed": revealed,
            "waiting_on_other": bool(mine) and not other_ids,
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
        else:
            # Not merely hidden from the UI — absent from the response.
            entry["others_committed"] = len(other_ids)

        if question["resolution"] in ("correct", "incorrect"):
            entry["scores"] = _score_question(question, history)
        out.append(entry)
    return {"message_id": str(message_id), "questions": out}


def _score_question(question, history) -> list[dict]:
    """Per-forecaster time-weighted Brier, once the outcome is known."""
    opened = min((h["recorded_at"] for h in history), default=None)
    scores = []
    for user_id in {h["user_id"] for h in history}:
        scored = time_weighted_brier(
            [
                {"recorded_at": h["recorded_at"], "confidence": h["confidence"]}
                for h in history if h["user_id"] == user_id
            ],
            opened=opened,
            close=question["deadline"],
            resolved_at=question["resolved_at"],
            resolution=question["resolution"],
        )
        if scored is None:
            continue
        scores.append({
            "user_id": str(user_id),
            **scored,
            "bss": brier_skill_score(scored["brier"], IGNORANCE_REF_BRIER),
        })
    return scores
