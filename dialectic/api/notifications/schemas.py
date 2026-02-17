# api/notifications/schemas.py - Push notification request/response schemas
"""
ARCHITECTURE: Pydantic models for notification endpoints.
WHY: Type-safe API contracts with automatic validation.
TRADEOFF: Explicit schemas vs dynamic dict handling (safety over flexibility).
"""

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class RegisterTokenRequest(BaseModel):
    """Request to register a push notification token."""
    expo_push_token: str = Field(..., description="Expo push token from device")
    platform: str = Field(..., pattern="^(ios|android)$", description="Device platform")
    device_name: Optional[str] = Field(None, description="Human-readable device name")


class UnregisterTokenRequest(BaseModel):
    """Request to unregister a push notification token."""
    expo_push_token: str = Field(..., description="Expo push token to unregister")


class MuteRoomRequest(BaseModel):
    """Request to update room notification mute settings."""
    muted: bool = Field(..., description="Whether notifications are muted")
    muted_until: Optional[datetime] = Field(None, description="Temporary mute expiry time")


class RoomNotificationSettingsResponse(BaseModel):
    """Response for room notification settings."""
    muted: bool = Field(..., description="Whether notifications are muted")
    muted_until: Optional[datetime] = Field(None, description="Temporary mute expiry time")


class BadgeResponse(BaseModel):
    """
    Response for badge count endpoint.

    ARCHITECTURE: total_unread_rooms is app badge (CONTEXT.md: rooms with unread).
    room_counts provides per-room badges for room list UI.
    """
    total_unread_rooms: int = Field(..., description="Count of rooms with unread messages (app badge)")
    room_counts: Dict[str, int] = Field(..., description="Unread message count per room_id")
