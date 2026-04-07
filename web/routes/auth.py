"""Auth routes — login only. No registration (hardcoded dev users)."""

from fastapi import APIRouter

from web.auth import login as do_login
from web.models import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    return do_login(req)
