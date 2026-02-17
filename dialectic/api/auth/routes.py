# api/auth/routes.py - Authentication API endpoints
"""
ARCHITECTURE: FastAPI router with all auth endpoints.
WHY: Complete auth lifecycle: signup, login, refresh, logout, email verification, password reset.
TRADEOFF: All auth in one file vs splitting by function (cohesion over granularity).
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

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

@router.post("/signup", response_model=TokenResponse)
async def signup(
    request: SignUpRequest,
    db=Depends(get_db),
):
    """
    Register a new user account.

    Creates user record, credentials, generates verification code, and returns tokens.
    Note: Email sending is out of scope - verification code is logged for now.
    """
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

    # Log verification code (email sending is out of scope)
    logger.info(f"Verification code for {request.email}: {verification_code}")

    # Create session and return tokens
    access_token = create_access_token(data={"sub": str(user_id)})
    refresh_token = create_refresh_token(data={"sub": str(user_id)})

    await _create_session(db, user_id, refresh_token, now)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: SignInRequest,
    db=Depends(get_db),
):
    """
    Authenticate user with email and password.

    Returns access and refresh tokens on success.
    """
    # Find user by email
    row = await db.fetchrow(
        """
        SELECT u.id, uc.password_hash, uc.email_verified
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

    # Verify session exists and is not revoked
    token_hash = hash_refresh_token(request.refresh_token)
    session = await db.fetchrow(
        """
        SELECT id, user_id FROM user_sessions
        WHERE refresh_token_hash = $1
          AND user_id = $2
          AND revoked_at IS NULL
          AND expires_at > NOW()
        """,
        token_hash, user_id
    )

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found or revoked"
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
        SET revoked_at = NOW()
        WHERE refresh_token_hash = $1 AND revoked_at IS NULL
        """,
        token_hash
    )

    # Always return success (don't leak session existence)
    return MessageResponse(message="Logged out successfully")


# ============================================================
# EMAIL VERIFICATION
# ============================================================

@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    request: VerifyEmailRequest,
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Verify email address using 6-digit code.

    Requires authentication (user must be logged in).
    """
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
    request: ForgotPasswordRequest,
    db=Depends(get_db),
):
    """
    Request a password reset code.

    Per CONTEXT.md: Returns 404 if no account exists (explicit error).
    """
    # Find user by email
    user_row = await db.fetchrow(
        "SELECT user_id FROM user_credentials WHERE email = $1",
        request.email.lower()
    )

    if user_row is None:
        # Per CONTEXT.md: explicit error if no account exists
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email address"
        )

    user_id = user_row["user_id"]
    now = datetime.now(timezone.utc)

    # Generate reset code (30 min expiry)
    reset_code = generate_verification_code()
    expires_at = now + timedelta(minutes=30)

    await db.execute(
        """
        INSERT INTO verification_codes (user_id, code, purpose, created_at, expires_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        user_id, reset_code, "password_reset", now, expires_at
    )

    # Log reset code (email sending is out of scope)
    logger.info(f"Password reset code for {request.email}: {reset_code}")

    return MessageResponse(
        message="Password reset code sent",
        detail="Check your email for the 6-digit code"
    )


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(
    request: ResetPasswordRequest,
    db=Depends(get_db),
):
    """
    Reset password using 6-digit code.

    Per CONTEXT.md: Auto-login after successful reset.
    Revokes all existing sessions for security.
    """
    # Find user by email
    user_row = await db.fetchrow(
        "SELECT user_id FROM user_credentials WHERE email = $1",
        request.email.lower()
    )

    if user_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email address"
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
        "UPDATE user_sessions SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL",
        user_id
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
                "UPDATE user_sessions SET revoked_at = NOW() WHERE id = $1",
                oldest["id"]
            )
            logger.info(f"Revoked oldest session for user {user_id} due to device limit")

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
