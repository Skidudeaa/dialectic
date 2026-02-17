# api/notifications/service.py - Push notification service
"""
ARCHITECTURE: Centralized push notification sending via Expo Push Service.
WHY: Encapsulates Expo SDK, token management, error handling in one place.
TRADEOFF: Synchronous sends; could batch for high volume.
"""

import logging
import os
from typing import Dict, List, Optional

from exponent_server_sdk import (
    DeviceNotRegisteredError,
    PushClient,
    PushMessage,
    PushServerError,
    PushTicketError,
)

logger = logging.getLogger(__name__)

# CONTEXT.md: Full message preview (up to ~200 chars)
MAX_BODY_LENGTH = 200
# CONTEXT.md: LLM messages distinguished with emoji
LLM_EMOJI = "\U0001F916"  # Robot emoji


class PushNotificationService:
    """
    ARCHITECTURE: Centralized push notification sending.
    WHY: Encapsulates Expo SDK, token management, error handling.
    TRADEOFF: Synchronous sends; could batch for high volume.
    """

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or os.getenv('EXPO_PUSH_ACCESS_TOKEN')
        self._client: Optional[PushClient] = None

    @property
    def client(self) -> PushClient:
        """Lazy-initialize PushClient with optional auth."""
        if self._client is None:
            import requests
            session = requests.Session()
            if self.access_token:
                session.headers.update({
                    'Authorization': f'Bearer {self.access_token}'
                })
            self._client = PushClient(session=session)
        return self._client

    async def send_message_notification(
        self,
        db,
        recipient_user_ids: List[str],
        room_id: str,
        thread_id: str,
        message_id: str,
        sender_name: str,
        content: str,
        is_llm: bool = False,
        badge_counts: Optional[Dict[str, int]] = None,
    ) -> dict:
        """
        Send push notification for a new message.

        Args:
            db: Database connection
            recipient_user_ids: Users to notify (excluding sender)
            room_id, thread_id, message_id: For deep linking
            sender_name: CONTEXT.md: Title shows sender name only
            content: CONTEXT.md: Full message preview (up to ~200 chars)
            is_llm: CONTEXT.md: LLM messages distinguished with emoji
            badge_counts: CONTEXT.md: Badge = rooms with unread (per user)
        """
        # Get push tokens for recipients
        tokens = await db.fetch(
            """SELECT user_id, expo_push_token FROM push_tokens
               WHERE user_id = ANY($1::uuid[]) AND is_active = true""",
            recipient_user_ids
        )

        if not tokens:
            return {'sent': 0, 'errors': []}

        # CONTEXT.md: Title shows sender name, LLM has emoji prefix
        title = f"{LLM_EMOJI} {sender_name}" if is_llm else sender_name

        # CONTEXT.md: Full message preview (up to ~200 chars)
        body = content[:MAX_BODY_LENGTH]
        if len(content) > MAX_BODY_LENGTH:
            body = body.rsplit(' ', 1)[0] + '...'

        # CONTEXT.md: Distinct sound for Claude vs human
        sound = 'llm_notification.wav' if is_llm else 'human_notification.wav'
        channel_id = 'llm_messages' if is_llm else 'human_messages'

        messages = []
        for row in tokens:
            user_id = str(row['user_id'])
            badge = badge_counts.get(user_id, 0) if badge_counts else None

            messages.append(PushMessage(
                to=row['expo_push_token'],
                title=title,
                body=body,
                sound=sound,
                badge=badge,
                data={
                    'room_id': room_id,
                    'thread_id': thread_id,
                    'message_id': message_id,
                    'type': 'new_message',
                },
                channel_id=channel_id,
                # CONTEXT.md: Multiple messages group per room
                thread_id=f"room_{room_id}",  # iOS grouping
            ))

        return await self._send_batch(db, messages)

    async def _send_batch(self, db, messages: List[PushMessage]) -> dict:
        """Send batch of messages, handle errors, invalidate bad tokens."""
        sent = 0
        errors = []

        try:
            # Expo allows up to 100 per request
            for i in range(0, len(messages), 100):
                batch = messages[i:i+100]
                responses = self.client.publish_multiple(batch)

                for msg, response in zip(batch, responses):
                    try:
                        response.validate_response()
                        sent += 1
                    except DeviceNotRegisteredError:
                        # Mark token as inactive
                        await db.execute(
                            """UPDATE push_tokens SET is_active = false
                               WHERE expo_push_token = $1""",
                            msg.to
                        )
                        errors.append({
                            'token': msg.to,
                            'error': 'device_not_registered'
                        })
                    except PushTicketError as e:
                        errors.append({
                            'token': msg.to,
                            'error': str(e)
                        })
        except PushServerError as e:
            logger.error(f"Push server error: {e}")
            errors.append({'error': str(e)})
        except Exception as e:
            logger.exception("Unexpected push error")
            errors.append({'error': str(e)})

        return {'sent': sent, 'errors': errors}


async def calculate_badge_count(db, user_id: str) -> int:
    """
    CONTEXT.md: Badge count = number of rooms with unread messages.
    Not total message count.
    """
    result = await db.fetchval(
        """
        SELECT COUNT(DISTINCT t.room_id)
        FROM messages m
        JOIN threads t ON m.thread_id = t.id
        JOIN room_memberships rm ON t.room_id = rm.room_id
        WHERE rm.user_id = $1
          AND m.user_id != $1
          AND m.speaker_type != 'SYSTEM'
          AND NOT EXISTS (
              SELECT 1 FROM message_receipts mr
              WHERE mr.message_id = m.id
                AND mr.user_id = $1
                AND mr.receipt_type = 'read'
          )
        """,
        user_id
    )
    return result or 0


async def get_room_unread_count(db, user_id: str, room_id: str) -> int:
    """
    CONTEXT.md: Numeric badge per room in room list.
    """
    result = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM messages m
        JOIN threads t ON m.thread_id = t.id
        WHERE t.room_id = $1
          AND m.user_id != $2
          AND m.speaker_type != 'SYSTEM'
          AND NOT EXISTS (
              SELECT 1 FROM message_receipts mr
              WHERE mr.message_id = m.id
                AND mr.user_id = $2
                AND mr.receipt_type = 'read'
          )
        """,
        room_id, user_id
    )
    return result or 0


async def get_all_room_unread_counts(db, user_id: str) -> Dict[str, int]:
    """
    Get unread message counts for all rooms the user is a member of.
    Used for badge endpoint per-room counts.
    """
    rows = await db.fetch(
        """
        SELECT t.room_id, COUNT(m.id) as unread_count
        FROM messages m
        JOIN threads t ON m.thread_id = t.id
        JOIN room_memberships rm ON t.room_id = rm.room_id
        WHERE rm.user_id = $1
          AND m.user_id != $1
          AND m.speaker_type != 'SYSTEM'
          AND NOT EXISTS (
              SELECT 1 FROM message_receipts mr
              WHERE mr.message_id = m.id
                AND mr.user_id = $1
                AND mr.receipt_type = 'read'
          )
        GROUP BY t.room_id
        """,
        user_id
    )
    return {str(row['room_id']): row['unread_count'] for row in rows}


# Singleton instance
push_service = PushNotificationService()
