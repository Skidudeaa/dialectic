# api/auth/routes.py - Authentication API endpoints
"""
ARCHITECTURE: FastAPI router with all auth endpoints.
WHY: Complete auth lifecycle: signup, login, refresh, logout, email verification, password reset.
TRADEOFF: All auth in one file vs splitting by function (cohesion over granularity).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.rate_limit import check_account_rate_limit, check_ip_rate_limit

from .schemas import (
    SignUpRequest,
    SignInRequest,
    RefreshRequest,
    VerifyEmailRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    MessageResponse,
)
from .utils import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_verification_code,
    hash_refresh_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from .dependencies import get_current_user, AuthenticatedUser


logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum active sessions per user (per CONTEXT.md: 3-5 devices)
MAX_SESSIONS_PER_USER = 5

# Why a session ended, persisted to user_sessions.revoked_reason and echoed
# to the client on refresh. WHY: all three used to surface as an identical
# flat 401, so a device evicted by the multi-device limit was indistinguishable
# from one whose token simply aged out — the app just dropped to a blank auth
# screen and the user assumed something was broken.
REVOKED_BY_LOGOUT = "logout"
REVOKED_BY_NEW_LOGIN = "evicted_by_new_login"
REVOKED_BY_PASSWORD_RESET = "password_reset"

# Client-facing copy per reason. Anything not listed here (including NULL, for
# sessions revoked before revoked_reason existed) falls back to a plain expiry.
REVOCATION_MESSAGES = {
    REVOKED_BY_NEW_LOGIN: (
        f"You were signed out because you signed in on another device. "
        f"Only {MAX_SESSIONS_PER_USER} devices can be signed in at once."
    ),
    REVOKED_BY_PASSWORD_RESET: "You were signed out because your password was changed.",
    REVOKED_BY_LOGOUT: "You signed out of this session.",
}


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

# This will be set by main.py when including the router
_db_pool = None


def set_db_pool(pool):
    """Set the database pool for auth routes."""
    global _db_pool
    _db_pool = pool


async def get_db():
    """Get a database connection from the pool."""
    if _db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    async with _db_pool.acquire() as conn:
        yield conn


# ============================================================
# SIGNUP / LOGIN / LOGOUT
# ============================================================

# WHY signup is gated: tradingDesk verifies Dialectic's access tokens with the
# same HS256 secret and maps the token's `sub` to a desk user. Signup was open
# to the internet. That combination means anyone who could self-register here
# held a token td would cryptographically trust — the only thing standing
# between them and the desk would be DIALECTIC_USER_MAP. Defence in depth says
# don't rely on that single list: close the door that mints the tokens.
#
# Fails CLOSED: the env var must explicitly say yes. Unset, empty, misspelled,
# or any unrecognised value all mean "closed", so a config mistake cannot
# silently reopen registration.
_SIGNUPS_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _signups_enabled() -> bool:
    """Read the flag at call time so the gate follows the environment the
    process is actually running in, not the one it imported under."""
    return os.environ.get("SIGNUPS_ENABLED", "").strip().lower() in _SIGNUPS_ENABLED_VALUES


@router.post("/signup", response_model=TokenResponse)
async def signup(
    http_request: Request,
    request: SignUpRequest,
    db=Depends(get_db),
):
    """
    Register a new user account.

    Disabled unless SIGNUPS_ENABLED is explicitly truthy — see the note above.

    Creates user record, credentials, generates verification code, and returns tokens.
    Note: Email sending is out of scope - verification code is logged for now.
    """
    check_ip_rate_limit(
        http_request,
        scope="signup",
        limit=5,
        window_seconds=3600,
    )

    # Checked before ANY database work: a refusal must not create rows, consume
    # a uuid, or reveal whether an email is already registered.
    if not _signups_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signups are closed. Ask Amo for an invite.",
        )

    # Check if email already exists
    existing = await db.fetchrow(
        "SELECT user_id FROM user_credentials WHERE email = $1",
        request.email.lower()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists"
        )

    # Create user record first
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    await db.execute(
        """
        INSERT INTO users (id, created_at, display_name)
        VALUES ($1, $2, $3)
        """,
        user_id, now, request.display_name
    )

    # Create credentials
    password_hashed = get_password_hash(request.password)

    await db.execute(
        """
        INSERT INTO user_credentials (user_id, email, email_verified, password_hash, created_at, updated_at)
        VALUES ($1, $2, FALSE, $3, $4, $4)
        """,
        user_id, request.email.lower(), password_hashed, now
    )

    # Generate verification code (30 min expiry)
    verification_code = generate_verification_code()
    expires_at = now + timedelta(minutes=30)

    await db.execute(
        """
        INSERT INTO verification_codes (user_id, code, purpose, created_at, expires_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        user_id, verification_code, "email_verification", now, expires_at
    )

    # NOTE: Email delivery not yet implemented. Code stored in DB for verification.
    # SECURITY: Never log verification codes — they are one-time auth credentials.
    logger.debug("Verification code generated for user %s", user_id)

    # Create session and return tokens
    access_token = create_access_token(data={"sub": str(user_id)})
    refresh_token = create_refresh_token(data={"sub": str(user_id)})

    await _create_session(db, user_id, refresh_token, now)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
        display_name=request.display_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    http_request: Request,
    request: SignInRequest,
    db=Depends(get_db),
):
    """
    Authenticate user with email and password.

    Returns access and refresh tokens on success.
    """
    check_account_rate_limit(
        http_request,
        request.email,
        scope="login",
        limit=5,
        window_seconds=900,
    )

    # Find user by email
    row = await db.fetchrow(
        """
        SELECT u.id, u.display_name, uc.password_hash, uc.email_verified
        FROM user_credentials uc
        JOIN users u ON uc.user_id = u.id
        WHERE uc.email = $1
        """,
        request.email.lower()
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password
    if not verify_password(request.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    user_id = row["id"]
    now = datetime.now(timezone.utc)

    # Create tokens
    access_token = create_access_token(data={"sub": str(user_id)})
    refresh_token = create_refresh_token(data={"sub": str(user_id)})

    await _create_session(db, user_id, refresh_token, now)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
        display_name=row["display_name"],
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshRequest,
    db=Depends(get_db),
):
    """
    Exchange a valid refresh token for a new access token.

    The same refresh token is returned (no rotation in this implementation).
    """
    try:
        payload = decode_token(request.refresh_token)

        # Verify this is a refresh token
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )

        user_id = UUID(payload["sub"])

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # Look the session up WITHOUT filtering on revoked_at, so a revoked one can
    # explain itself instead of being indistinguishable from a bad token.
    token_hash = hash_refresh_token(request.refresh_token)
    session = await db.fetchrow(
        """
        SELECT id, user_id, revoked_at, revoked_reason, (expires_at > NOW()) AS unexpired
        FROM user_sessions
        WHERE refresh_token_hash = $1 AND user_id = $2
        """,
        token_hash, user_id
    )

    if session is None or not session["unexpired"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found or revoked"
        )

    if session["revoked_at"] is not None:
        # `detail` carries the human-readable copy because authFetch on the
        # client already surfaces it verbatim; the header carries the machine
        # code for anything that wants to branch on it. An unrecognised or
        # NULL reason (sessions revoked before this column existed) falls back
        # to the generic message rather than inventing an explanation.
        reason = session["revoked_reason"]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REVOCATION_MESSAGES.get(reason, "Session not found or revoked"),
            headers={"X-Session-Revoked-Reason": reason} if reason else None,
        )

    # Update last_used_at
    await db.execute(
        "UPDATE user_sessions SET last_used_at = NOW() WHERE id = $1",
        session["id"]
    )

    # Generate new access token (keep same refresh token)
    access_token = create_access_token(data={"sub": str(user_id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=request.refresh_token,
        user_id=user_id,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: RefreshRequest,
    db=Depends(get_db),
):
    """
    Revoke the current session (invalidate refresh token).
    """
    token_hash = hash_refresh_token(request.refresh_token)

    result = await db.execute(
        """
        UPDATE user_sessions
        SET revoked_at = NOW(), revoked_reason = $2
        WHERE refresh_token_hash = $1 AND revoked_at IS NULL
        """,
        token_hash, REVOKED_BY_LOGOUT
    )

    # Always return success (don't leak session existence)
    return MessageResponse(message="Logged out successfully")


# ============================================================
# EMAIL VERIFICATION
# ============================================================

@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    http_request: Request,
    request: VerifyEmailRequest,
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Verify email address using 6-digit code.

    Requires authentication (user must be logged in).
    """
    check_account_rate_limit(
        http_request,
        str(current_user.user_id),
        scope="verify-email",
        limit=5,
        window_seconds=900,
    )

    # Find valid, unused code for this user
    code_row = await db.fetchrow(
        """
        SELECT id FROM verification_codes
        WHERE user_id = $1
          AND code = $2
          AND purpose = 'email_verification'
          AND used_at IS NULL
          AND expires_at > NOW()
        ORDER BY created_at DESC
        LIMIT 1
        """,
        current_user.user_id, request.code
    )

    if code_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code"
        )

    # Mark code as used and email as verified
    await db.execute(
        "UPDATE verification_codes SET used_at = NOW() WHERE id = $1",
        code_row["id"]
    )

    await db.execute(
        "UPDATE user_credentials SET email_verified = TRUE, updated_at = NOW() WHERE user_id = $1",
        current_user.user_id
    )

    return MessageResponse(message="Email verified successfully")


# ============================================================
# PASSWORD RESET
# ============================================================

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    http_request: Request,
    request: ForgotPasswordRequest,
):
    """
    Report that password recovery is unavailable without email delivery.
    """
    check_account_rate_limit(
        http_request,
        request.email,
        scope="forgot-password",
        limit=3,
        window_seconds=900,
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Password recovery is unavailable because email delivery is not configured",
    )


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(
    http_request: Request,
    request: ResetPasswordRequest,
    db=Depends(get_db),
):
    """
    Reset password using 6-digit code.

    Per CONTEXT.md: Auto-login after successful reset.
    Revokes all existing sessions for security.
    """
    check_account_rate_limit(
        http_request,
        request.email,
        scope="reset-password",
        limit=5,
        window_seconds=900,
    )

    # Find user by email
    user_row = await db.fetchrow(
        "SELECT user_id FROM user_credentials WHERE email = $1",
        request.email.lower()
    )

    if user_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset code"
        )

    user_id = user_row["user_id"]

    # Verify code
    code_row = await db.fetchrow(
        """
        SELECT id FROM verification_codes
        WHERE user_id = $1
          AND code = $2
          AND purpose = 'password_reset'
          AND used_at IS NULL
          AND expires_at > NOW()
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id, request.code
    )

    if code_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset code"
        )

    now = datetime.now(timezone.utc)

    # Mark code as used
    await db.execute(
        "UPDATE verification_codes SET used_at = NOW() WHERE id = $1",
        code_row["id"]
    )

    # Update password
    new_password_hash = get_password_hash(request.new_password)
    await db.execute(
        "UPDATE user_credentials SET password_hash = $1, updated_at = $2 WHERE user_id = $3",
        new_password_hash, now, user_id
    )

    # Revoke all existing sessions for security
    await db.execute(
        """
        UPDATE user_sessions
        SET revoked_at = NOW(), revoked_reason = $2
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        user_id, REVOKED_BY_PASSWORD_RESET
    )

    # Auto-login: create new session
    access_token = create_access_token(data={"sub": str(user_id)})
    refresh_token = create_refresh_token(data={"sub": str(user_id)})

    await _create_session(db, user_id, refresh_token, now)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
    )


# ============================================================
# HELPERS
# ============================================================

async def _create_session(db, user_id: UUID, refresh_token: str, now: datetime):
    """
    Create a new session for the user.

    Enforces multi-device limit: if >= MAX_SESSIONS_PER_USER,
    revokes the oldest session (by last_used_at).
    """
    # Count active sessions
    session_count = await db.fetchval(
        """
        SELECT COUNT(*) FROM user_sessions
        WHERE user_id = $1 AND revoked_at IS NULL AND expires_at > NOW()
        """,
        user_id
    )

    # If at limit, revoke oldest session
    if session_count >= MAX_SESSIONS_PER_USER:
        oldest = await db.fetchrow(
            """
            SELECT id FROM user_sessions
            WHERE user_id = $1 AND revoked_at IS NULL AND expires_at > NOW()
            ORDER BY last_used_at ASC
            LIMIT 1
            """,
            user_id
        )
        if oldest:
            await db.execute(
                """
                UPDATE user_sessions
                SET revoked_at = NOW(), revoked_reason = $2
                WHERE id = $1
                """,
                oldest["id"], REVOKED_BY_NEW_LOGIN
            )
            logger.info(
                f"Revoked oldest session for user {user_id} due to device limit "
                f"(session {oldest['id']}); that device will be told why on its next refresh"
            )

    # Create new session
    token_hash = hash_refresh_token(refresh_token)
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    await db.execute(
        """
        INSERT INTO user_sessions (user_id, refresh_token_hash, created_at, last_used_at, expires_at)
        VALUES ($1, $2, $3, $3, $4)
        """,
        user_id, token_hash, now, expires_at
    )
