"""
JWT authentication for the trading desk web layer.

WHY: Two-analyst workspace — hardcoded dev users, no registration flow.
JWT tokens carry username + display_name. Middleware validates on all
/api/* routes except /api/auth/login and /api/health.
"""

import hashlib
import os
import uuid as _uuid
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from web.models import LoginRequest, LoginResponse, User

# WHY: Default secret for dev. Production MUST override via env var.
JWT_SECRET = os.environ.get("JWT_SECRET", "tradingdesk-dev-secret-change-me")
if JWT_SECRET == "tradingdesk-dev-secret-change-me":
    import warnings
    warnings.warn(
        "JWT_SECRET is using the default dev value — set JWT_SECRET env var for production",
        stacklevel=2,
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72


# WHY: Per-user salt + scrypt key derivation. stdlib-only (no bcrypt).
# Even for two hardcoded users, unsalted SHA-256 is indefensible if the
# hash is ever exposed — scrypt costs nothing at this scale.
_SALT = b"tradingdesk-v1"  # Fixed salt is acceptable for hardcoded-user dev workspace

def _hash_password(password: str) -> str:
    """Derive a scrypt hash. Fixed salt is acceptable for hardcoded dev users."""
    dk = hashlib.scrypt(password.encode(), salt=_SALT, n=2**14, r=8, p=1, dklen=32)
    return dk.hex()


# WHY: Hardcoded dev users — small trading desk, not a SaaS. All users share
# the same privileges; there is no admin role.
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
    "salloum": {
        "username": "salloum",
        "display_name": "Salloum",
        "hashed_password": _hash_password(_default_pw),
    },
}

# WHY: Dialectic's LLM participant calls this API through a dedicated service
# principal so the agent's calls are attributed to the agent (agent log,
# prediction authorship) rather than borrowing a human's credentials.
# Registered ONLY when the env var is set — absent var, absent user.
_service_pw = os.environ.get("DIALECTIC_SERVICE_PASSWORD")
if _service_pw:
    DEV_USERS["dialectic"] = {
        "username": "dialectic",
        "display_name": "Dialectic (Claude)",
        "hashed_password": _hash_password(_service_pw),
    }

security = HTTPBearer(auto_error=False)


# ============================================================
# DIALECTIC TOKEN BRIDGE
# ============================================================
# WHY: Dialectic and this desk are one workspace shared by the same two
# analysts. Rather than make Amo and Dan hold two logins, td accepts a
# Dialectic ACCESS token as proof of identity: both services verify HS256
# with the SAME secret, so a token Dialectic minted is one td can check.
#
# The two shapes are told apart by an EXPLICIT claim, never by guessing:
#   Dialectic access token: {"sub": "<user uuid>", "type": "access", iat, exp}
#   td token:               {"sub": "<username>", "name": "<display>", exp}
# td has never issued a `type` claim, so its presence is the tell and local
# logins are untouched.
#
# TRADEOFF: a shared secret means a Dialectic signing-key compromise is a td
# compromise. Accepted because it is one owner, one box, two apps — and it is
# why Dialectic's open signup had to be closed in the same change (an account
# anyone could self-register for would otherwise mint a td-valid token).
DIALECTIC_ACCESS_TYPE = "access"


def _parse_dialectic_user_map(raw: str) -> dict:
    """
    Parse `uuid:username,uuid:username` into {canonical_uuid: username}.

    Malformed entries are warned about and skipped rather than raised: a typo
    in one pair must not take the whole desk's authentication offline at boot.
    An empty/absent value simply yields {}, which disables the bridge (every
    Dialectic token then 401s with an explicit "not mapped" detail).
    """
    mapping: dict = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        raw_uuid, sep, username = pair.partition(":")
        if not sep or not username.strip():
            warnings.warn(
                f"DIALECTIC_USER_MAP: skipping malformed entry {pair!r} "
                "(expected uuid:username)",
                stacklevel=2,
            )
            continue
        try:
            # Canonicalise so casing/formatting differences in the env var
            # cannot silently fail to match the token's `sub`.
            key = str(_uuid.UUID(raw_uuid.strip()))
        except ValueError:
            warnings.warn(
                f"DIALECTIC_USER_MAP: skipping entry with non-UUID key {raw_uuid!r}",
                stacklevel=2,
            )
            continue
        mapping[key] = username.strip().lower()
    return mapping


DIALECTIC_USER_MAP = _parse_dialectic_user_map(
    os.environ.get("DIALECTIC_USER_MAP", "")
)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_dialectic_token(payload: dict) -> dict:
    """
    Translate a verified Dialectic token into a td-shaped payload.

    Called only for tokens carrying a `type` claim. Returns a payload whose
    `sub` is the td username, so every caller downstream — including
    get_current_user — sees an ordinary local identity. The Dialectic user id
    is preserved under `dialectic_user_id` for logging/attribution.

    Raises 401 (never falls through to the local path) for any token that is
    Dialectic-shaped but not usable, so a refused bridge token can never be
    mistaken for a td username.
    """
    token_type = payload.get("type")
    if token_type != DIALECTIC_ACCESS_TYPE:
        # WHY reject refresh tokens explicitly: Dialectic's refresh token is
        # valid for 90 days and exists only to renew a session. Honouring one
        # here would silently turn a renewal secret into a long-lived API key.
        raise _unauthorized(
            f"Token type '{token_type}' is not accepted for API access"
        )

    raw_sub = str(payload["sub"]).strip()
    try:
        dialectic_id = str(_uuid.UUID(raw_sub))
    except ValueError:
        raise _unauthorized("Token is not a recognized Dialectic identity")

    username = DIALECTIC_USER_MAP.get(dialectic_id)
    if username is None:
        raise _unauthorized(
            "This Dialectic account is not authorized for tradingDesk. "
            "Ask Amo to add it to DIALECTIC_USER_MAP."
        )

    local_user = DEV_USERS.get(username)
    if local_user is None:
        # A map entry pointing at a username this desk does not have would
        # otherwise conjure a principal with no account behind it.
        raise _unauthorized(
            f"Mapped tradingDesk user '{username}' does not exist"
        )

    bridged = dict(payload)
    bridged["sub"] = local_user["username"]
    bridged["name"] = local_user["display_name"]
    bridged["dialectic_user_id"] = dialectic_id
    return bridged


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
    """
    Decode and validate a JWT. Raises on invalid/expired.

    Accepts two issuers, both verified against the same HS256 secret:
    td's own tokens (returned unchanged) and Dialectic access tokens, which
    are translated to a td identity by _resolve_dialectic_token. Callers
    always receive a payload whose `sub` is a local username.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if "sub" not in payload:
            raise JWTError("Missing sub claim")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # A `type` claim means this was not minted by td's create_access_token.
    # Note this sits OUTSIDE the try above on purpose: the 401s raised by
    # _resolve_dialectic_token are already HTTPExceptions and must reach the
    # client with their own explanatory detail, not be flattened into the
    # generic "Invalid or expired token".
    if "type" in payload:
        return _resolve_dialectic_token(payload)

    return payload


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """
    FastAPI dependency — extracts User from Bearer token.

    Works for both issuers: decode_token has already translated a Dialectic
    access token into a local username + display name by the time we read it.
    """
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
