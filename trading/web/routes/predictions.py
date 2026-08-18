"""Prediction tracker CRUD routes with real-time broadcasts."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from web import scoring
from web.auth import get_current_user
from web.deps import get_repo
from web.models import (
    User,
    PredictionConfidenceCreate,
    PredictionCreate,
    PredictionResolve,
)
from web.persistence.repository import (
    PredictionAlreadyResolved,
    PredictionResolutionConflict,
    Repository,
)
from web.ws import manager

router = APIRouter(prefix="/api/predictions", tags=["predictions"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_predictions(repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_predictions)


# WHY these two GETs sit above /{prediction_id}: FastAPI matches routes in
# registration order, so registered later they would match as prediction
# ids and 404.

@router.get("/leaderboard")
async def prediction_leaderboard(
    split_by: str = "source_label",
    repo: Repository = Depends(get_repo),
) -> dict:
    if split_by not in scoring.LEADERBOARD_SPLITS:
        raise HTTPException(
            status_code=422,
            detail=f"split_by must be one of {list(scoring.LEADERBOARD_SPLITS)}",
        )
    rows = await asyncio.to_thread(repo.list_predictions)
    return {"split_by": split_by, "groups": scoring.leaderboard(rows, split_by)}


@router.get("/calibration")
async def prediction_calibration(
    source_label: Optional[str] = None,
    repo: Repository = Depends(get_repo),
) -> dict:
    rows = await asyncio.to_thread(repo.list_predictions)
    if source_label is not None:
        rows = [r for r in rows if r.get("source_label") == source_label]
    result = scoring.calibration_buckets(rows)
    result["source_label"] = source_label
    return result


@router.get("/{prediction_id}")
async def get_prediction(prediction_id: str, repo: Repository = Depends(get_repo)) -> dict:
    for p in await asyncio.to_thread(repo.list_predictions):
        if p.get("id") == prediction_id:
            return p
    raise HTTPException(status_code=404, detail="Prediction not found")


@router.post("")
async def create_prediction(req: PredictionCreate, user: User = Depends(get_current_user),
                            repo: Repository = Depends(get_repo)) -> dict:
    prediction, created = await asyncio.to_thread(
        repo.save_prediction_once,
        user.username,
        req.model_dump(),
    )
    if created:
        # A replay returns the existing entity and must not emit it twice.
        await manager.broadcast_all(
            "system",
            {"detail": f"{user.display_name} predicted: \"{req.statement}\" ({int(req.confidence * 100)}% by {req.deadline})"},
            user="system",
        )
    return prediction


@router.post("/{prediction_id}/resolve")
async def resolve_prediction(
    prediction_id: str,
    req: PredictionResolve,
    user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> dict:
    try:
        result, changed = await asyncio.to_thread(
            repo.resolve_prediction_once,
            prediction_id,
            req.resolution,
            req.source_key,
            req.resolution_notes,
        )
    except PredictionResolutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if changed:
        await manager.broadcast_all(
            "system",
            {"detail": f"Prediction resolved as {req.resolution}: \"{result.get('statement', '')[:60]}\""},
            user="system",
        )
    return result


@router.post("/{prediction_id}/confidence")
async def append_prediction_confidence(
    prediction_id: str,
    req: PredictionConfidenceCreate,
    user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> dict:
    try:
        entry = await asyncio.to_thread(
            repo.record_prediction_confidence,
            prediction_id,
            user.username,
            req.confidence,
            req.reasoning,
        )
    except PredictionAlreadyResolved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    await manager.broadcast_all(
        "system",
        {"detail": f"{user.display_name} updated confidence to {int(req.confidence * 100)}%"},
        user="system",
    )
    return entry
