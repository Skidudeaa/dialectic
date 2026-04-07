"""Prediction tracker CRUD routes."""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, PredictionCreate, PredictionResolve
from web import state

router = APIRouter(prefix="/api/predictions", tags=["predictions"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_predictions() -> list:
    return state.list_predictions()


@router.post("")
async def create_prediction(req: PredictionCreate, user: User = Depends(get_current_user)) -> dict:
    return state.save_prediction(user.username, req.model_dump())


@router.post("/{prediction_id}/resolve")
async def resolve_prediction(prediction_id: str, req: PredictionResolve) -> dict:
    result = state.resolve_prediction(prediction_id, req.resolution)
    if result is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return result
