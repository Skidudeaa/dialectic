# api/notifications/__init__.py - Push notification module exports
"""
ARCHITECTURE: Centralized notification service with REST endpoints.
WHY: Push notifications enable background message delivery to mobile devices.
TRADEOFF: Expo Push Service abstraction vs direct FCM/APNs (simplicity over control).
"""

from .service import push_service, calculate_badge_count, get_room_unread_count
from .routes import router as notifications_router

__all__ = ['push_service', 'calculate_badge_count', 'get_room_unread_count', 'notifications_router']
