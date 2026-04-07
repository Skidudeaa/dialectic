"""
JWT authentication for the trading desk web layer.

WHY: Two-analyst workspace — hardcoded dev users, no registration flow.
JWT tokens carry username + display_name. Middleware validates on all
/api/* routes except /api/auth/login and /api/health.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from web.models import LoginRequest, LoginResponse, User

# WHY: Default secret for dev. Production MUST override via env var.
JWT_SECRET = os.environ.get("JWT_SECRET", "tradingdesk-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72


def _hash_password(password: str) -> str:
    """WHY: SHA-256 is sufficient for a two-user dev workspace with no registration.
    Not a SaaS — no brute-force surface. Keep it stdlib-only to avoid bcrypt
    version conflicts across Python 3.10–3.12."""
    return hashlib.sha256(password.encode()).hexdigest()


# WHY: Hardcoded dev users — this is a two-person trading desk, not a SaaS.
# Passwords default to env var or "changeme" for dev.
_default_pw = os.environ.get("DEV_USER_PASSWORD", "changeme")
DEV_USERS = {
    "amo": {
        "username": "amo",
        "display_name": "Amo",
        "hashed_password": _hash_password(_default_pw),
    },
    "dan": {
        "username": "dan",
        "display_name": "Dan",
        "hashed_password": _hash_password(_default_pw),
    },
}

security = HTTPBearer(auto_error=False)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Verify credentials against hardcoded users."""
    user = DEV_USERS.get(username.lower())
    if not user:
        return None
    if _hash_password(password) != user["hashed_password"]:
        return None
    return user


def create_access_token(username: str, display_name: str) -> str:
    """Create a JWT with username and display_name claims."""
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "name": display_name,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises on invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if "sub" not in payload:
            raise JWTError("Missing sub claim")
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """FastAPI dependency — extracts User from Bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    return User(username=payload["sub"], display_name=payload.get("name", payload["sub"]))


def login(req: LoginRequest) -> LoginResponse:
    """Authenticate and return JWT."""
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_access_token(user["username"], user["display_name"])
    return LoginResponse(
        access_token=token,
        username=user["username"],
        display_name=user["display_name"],
    )
