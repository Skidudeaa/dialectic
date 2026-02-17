# api/notifications/routes.py - Push notification REST endpoints
"""
ARCHITECTURE: FastAPI router for push notification token management.
WHY: REST endpoints for token registration/unregistration and room mute settings.
TRADEOFF: Separate router vs inline in main.py (modularity over simplicity).
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from .schemas import (
    RegisterTokenRequest,
    UnregisterTokenRequest,
    MuteRoomRequest,
    RoomNotificationSettingsResponse,
    BadgeResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

# This will be set by main.py when including the router
_db_pool = None


def set_notifications_db_pool(pool):
    """Set the database pool for notification routes."""
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
# AUTH DEPENDENCY
# ============================================================

# Import from auth module
from api.auth.dependencies import get_current_user, AuthenticatedUser


async def get_current_user_with_db(
    db=Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Wrapper to ensure db is available when getting current user."""
    return user


# ============================================================
# TOKEN ENDPOINTS
# ============================================================

@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def register_push_token(
    request: RegisterTokenRequest,
    user: AuthenticatedUser = Depends(get_current_user_with_db),
    db=Depends(get_db),
):
    """
    Register or update a push token for the current user.

    Upsert: INSERT ... ON CONFLICT DO UPDATE to handle re-registration.
    Sets is_active = true and updates platform/device_name/updated_at.
    """
    await db.execute(
        """
        INSERT INTO push_tokens (user_id, expo_push_token, platform, device_name, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (user_id, expo_push_token)
        DO UPDATE SET platform = $3, device_name = $4, is_active = true, updated_at = NOW()
        """,
        user.user_id, request.expo_push_token, request.platform, request.device_name
    )
    return {"status": "registered"}


@router.delete("/tokens")
async def unregister_push_token(
    request: UnregisterTokenRequest,
    user: AuthenticatedUser = Depends(get_current_user_with_db),
    db=Depends(get_db),
):
    """
    Mark a push token as inactive.

    Does not delete the token, just marks it inactive to avoid re-use.
    """
    await db.execute(
        """
        UPDATE push_tokens SET is_active = false, updated_at = NOW()
        WHERE user_id = $1 AND expo_push_token = $2
        """,
        user.user_id, request.expo_push_token
    )
    return {"status": "unregistered"}


# ============================================================
# ROOM NOTIFICATION SETTINGS
# ============================================================

@router.put("/rooms/{room_id}/mute")
async def update_room_mute(
    room_id: UUID,
    request: MuteRoomRequest,
    user: AuthenticatedUser = Depends(get_current_user_with_db),
    db=Depends(get_db),
):
    """
    Update mute settings for a room (CONTEXT.md: per-room mute option).

    Upsert: INSERT ... ON CONFLICT DO UPDATE to handle new/existing settings.
    """
    # Verify user is a member of the room
    membership = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user.user_id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this room"
        )

    await db.execute(
        """
        INSERT INTO room_notification_settings (user_id, room_id, muted, muted_until)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id, room_id)
        DO UPDATE SET muted = $3, muted_until = $4
        """,
        user.user_id, room_id, request.muted, request.muted_until
    )
    return {"status": "updated"}


@router.get("/rooms/{room_id}/settings", response_model=RoomNotificationSettingsResponse)
async def get_room_notification_settings(
    room_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user_with_db),
    db=Depends(get_db),
):
    """
    Get notification settings for a room.

    Returns muted status and optional muted_until time.
    """
    # Verify user is a member of the room
    membership = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user.user_id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this room"
        )

    row = await db.fetchrow(
        "SELECT muted, muted_until FROM room_notification_settings WHERE user_id = $1 AND room_id = $2",
        user.user_id, room_id
    )

    if row:
        return RoomNotificationSettingsResponse(
            muted=row['muted'],
            muted_until=row['muted_until'],
        )
    else:
        # Default: not muted
        return RoomNotificationSettingsResponse(
            muted=False,
            muted_until=None,
        )


# ============================================================
# BADGE ENDPOINT
# ============================================================

@router.get("/badge", response_model=BadgeResponse)
async def get_badge_counts(
    user: AuthenticatedUser = Depends(get_current_user_with_db),
    db=Depends(get_db),
):
    """
    Get badge counts for mobile app sync.

    Returns total rooms with unread messages and per-room counts.
    Called by mobile app on foreground to sync badge state.
    """
    from .service import calculate_badge_count, get_all_room_unread_counts

    total_unread_rooms = await calculate_badge_count(db, str(user.user_id))
    room_counts = await get_all_room_unread_counts(db, str(user.user_id))

    return BadgeResponse(
        total_unread_rooms=total_unread_rooms,
        room_counts=room_counts,
    )
