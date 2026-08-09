"""Auth routes — login, Dialectic token exchange, whoami. No registration
(hardcoded dev users)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from web.auth import exchange_dialectic_token, get_current_user, security
from web.auth import login as do_login
from web.models import LoginRequest, LoginResponse, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    return do_login(req)


@router.post("/exchange", response_model=LoginResponse)
async def exchange(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> LoginResponse:
    """
    Trade a Dialectic access token for a td-native 72h token.

    WHY this is a separate endpoint rather than a claim on /login: the caller
    has no password. It arrives holding ONLY the bridge token — which is the
    whole point of the deep link — so the credential is the Authorization
    header, and the only thing being asked for is a longer-lived equivalent
    of the identity that header already proves.

    Deliberately NOT behind get_current_user: that dependency would happily
    accept a td token too, and the 400 for "already native" has to be decided
    by the exchange itself.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return exchange_dialectic_token(credentials.credentials)


@router.get("/me", response_model=User)
async def me(user: User = Depends(get_current_user)) -> User:
    """Who this bearer is. WHY: a bridged client is handed a token, never a
    username — without this it can only render an anonymous 'operator'."""
    return user
