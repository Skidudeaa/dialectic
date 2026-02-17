# api/auth/dependencies.py - FastAPI authentication dependencies
"""
ARCHITECTURE: Dependency injection for route protection.
WHY: Declarative auth requirements per-endpoint via Depends().
TRADEOFF: Database lookup per request vs caching (simplicity over optimization).
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError

from .utils import decode_token


# OAuth2 scheme extracts Bearer token from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthenticatedUser:
    """
    Represents an authenticated user from a valid JWT.
    Contains minimal info needed for authorization decisions.
    """
    def __init__(
        self,
        user_id: UUID,
        email: str,
        email_verified: bool,
        display_name: str,
    ):
        self.user_id = user_id
        self.email = email
        self.email_verified = email_verified
        self.display_name = display_name


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db = None,  # Will be injected in routes
) -> AuthenticatedUser:
    """
    Dependency that extracts and validates the current user from JWT.

    Raises:
        HTTPException 401: If token is invalid, expired, or not an access token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)

        # Verify this is an access token, not a refresh token
        if payload.get("type") != "access":
            raise credentials_exception

        user_id_str: Optional[str] = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception

        user_id = UUID(user_id_str)

    except (InvalidTokenError, ValueError):
        raise credentials_exception

    # If db is provided, fetch full user data
    if db is not None:
        row = await db.fetchrow(
            """
            SELECT u.id, u.display_name, uc.email, uc.email_verified
            FROM users u
            JOIN user_credentials uc ON u.id = uc.user_id
            WHERE u.id = $1
            """,
            user_id
        )
        if row is None:
            raise credentials_exception

        return AuthenticatedUser(
            user_id=row["id"],
            email=row["email"],
            email_verified=row["email_verified"],
            display_name=row["display_name"],
        )

    # Fallback: return minimal user from token claims
    return AuthenticatedUser(
        user_id=user_id,
        email=payload.get("email", ""),
        email_verified=payload.get("email_verified", False),
        display_name=payload.get("display_name", ""),
    )


async def get_current_verified_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """
    Dependency that requires both authentication AND email verification.

    Raises:
        HTTPException 403: If user's email is not verified.
    """
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        )
    return user
