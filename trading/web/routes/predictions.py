"""Prediction tracker CRUD routes with real-time broadcasts."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.deps import get_repo
from web.models import User, PredictionCreate, PredictionResolve
from web.persistence.repository import PredictionResolutionConflict, Repository
from web.ws import manager

router = APIRouter(prefix="/api/predictions", tags=["predictions"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_predictions(repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_predictions)


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
        )
    except PredictionResolutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if changed:
        icon = "correct" if req.resolution == "correct" else "incorrect"
        await manager.broadcast_all(
            "system",
            {"detail": f"Prediction resolved as {icon}: \"{result.get('statement', '')[:60]}\""},
            user="system",
        )
    return result
