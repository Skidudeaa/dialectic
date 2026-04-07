"""Prediction tracker CRUD routes with real-time broadcasts."""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, PredictionCreate, PredictionResolve
from web import state
from web.ws import manager

router = APIRouter(prefix="/api/predictions", tags=["predictions"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_predictions() -> list:
    return state.list_predictions()


@router.post("")
async def create_prediction(req: PredictionCreate, user: User = Depends(get_current_user)) -> dict:
    prediction = state.save_prediction(user.username, req.model_dump())
    # WHY: Broadcast to all connected users so prediction panels update in real-time.
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
) -> dict:
    result = state.resolve_prediction(prediction_id, req.resolution)
    if result is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    icon = "correct" if req.resolution == "correct" else "incorrect"
    await manager.broadcast_all(
        "system",
        {"detail": f"Prediction resolved as {icon}: \"{result.get('statement', '')[:60]}\""},
        user="system",
    )
    return result
