# Phase 6: Push Notifications - Research

**Researched:** 2026-01-25
**Domain:** Expo push notifications with FCM/APNs, badge management, custom sounds, deep linking
**Confidence:** HIGH

## Summary

This research covers push notification implementation for a React Native/Expo SDK 54 mobile app with a FastAPI backend. The phase requires background push notifications with message previews, app icon badges showing unread room counts, custom notification sounds (distinct for human vs LLM messages), notification grouping by room, and deep linking to specific messages.

Expo SDK 54 introduces a critical change: push notifications no longer work in Expo Go. Testing requires development builds (EAS Build). The `expo-notifications` library provides a unified API for both iOS and Android, integrating with Expo's Push Service which wraps FCM (Android) and APNs (iOS).

The backend will use `exponent-server-sdk-python` to send push notifications through Expo's Push API. Token storage, badge count calculation, and notification delivery must be integrated with the existing WebSocket infrastructure so that messages received via WebSocket don't trigger redundant push notifications (foreground suppression).

**Primary recommendation:** Use `expo-notifications` with `expo-device` for client-side implementation. Store Expo Push Tokens per user-device pair in PostgreSQL. Backend sends notifications via Expo Push Service when messages arrive for backgrounded users. Badge counts are calculated server-side (rooms with unread messages) and sent with each notification. Custom sounds configured via app.config.ts plugin. Deep linking uses expo-router with notification response listeners.

## Standard Stack

### Core (Mobile)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `expo-notifications` | ~1.0.x | Push/local notifications | Unified API for FCM/APNs, Expo SDK 54 native |
| `expo-device` | ~8.0.x | Device type detection | Required for push token validation |
| `expo-constants` | ~18.0.x | App config access | Required for projectId retrieval |
| `expo-router` | ~6.0.x | Navigation (already installed) | Deep linking from notifications |

### Core (Backend)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `exponent-server-sdk` | ^2.x | Expo Push API client | Official Python SDK, handles auth/batching |
| `httpx` | existing | Async HTTP (fallback) | Already used, can call Expo API directly |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `expo-task-manager` | ~13.0.x | Background tasks | Only if headless notification handling needed |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Expo Push Service | Direct FCM/APNs | More control but complex credential management |
| `exponent-server-sdk` | Direct HTTP to Expo API | SDK handles batching, retries, error parsing |
| Badge via notification | Client-side badge | Server-side is more reliable for background |

**Installation (Mobile):**
```bash
cd mobile
npx expo install expo-notifications expo-device
```

**Installation (Backend):**
```bash
pip install exponent-server-sdk
```

## Architecture Patterns

### Recommended Project Structure

```
mobile/
├── services/
│   └── notifications/
│       ├── index.ts              # NotificationService singleton
│       ├── handlers.ts           # Notification event handlers
│       ├── registration.ts       # Token registration with backend
│       └── deep-link.ts          # Navigation from notification tap
├── stores/
│   └── notification-store.ts     # Badge count, mute settings
├── hooks/
│   └── use-notifications.ts      # Permission & setup hook
└── app.config.ts                 # Add expo-notifications plugin

dialectic/
├── api/
│   └── notifications/
│       ├── routes.py             # Token registration endpoints
│       ├── service.py            # Push sending logic
│       └── schemas.py            # Token/notification models
├── transport/
│   └── handlers.py               # Extend to trigger push on message
└── schema.sql                    # Add push_tokens table
```

### Pattern 1: Push Token Registration

**What:** Register device push tokens with backend
**When to use:** App launch, token refresh, user login

```typescript
// Source: Expo docs + CONTEXT.md decisions
// services/notifications/registration.ts
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { api } from '@/services/api';
import { Platform } from 'react-native';

export async function registerForPushNotifications(userId: string): Promise<string | null> {
  // Must be physical device
  if (!Device.isDevice) {
    console.warn('Push notifications require a physical device');
    return null;
  }

  // Request permission
  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync({
      ios: {
        allowAlert: true,
        allowBadge: true,
        allowSound: true,
      },
    });
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    console.warn('Push notification permission denied');
    return null;
  }

  // Get Expo push token
  const projectId = Constants.expoConfig?.extra?.eas?.projectId
    ?? Constants.easConfig?.projectId;

  if (!projectId) {
    throw new Error('Missing projectId in app config');
  }

  const tokenData = await Notifications.getExpoPushTokenAsync({ projectId });
  const expoPushToken = tokenData.data;

  // Register with backend
  await api.post('/notifications/tokens', {
    expo_push_token: expoPushToken,
    platform: Platform.OS,
    device_name: Device.deviceName,
  });

  return expoPushToken;
}

export async function unregisterPushToken(expoPushToken: string): Promise<void> {
  await api.delete('/notifications/tokens', {
    data: { expo_push_token: expoPushToken },
  });
}
```

### Pattern 2: Notification Handler Setup

**What:** Configure notification behavior and event listeners
**When to use:** App root layout initialization

```typescript
// Source: Expo docs + CONTEXT.md decisions
// services/notifications/handlers.ts
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';

/**
 * Configure how notifications appear when app is foregrounded.
 * CONTEXT.md: Suppress if user is in the same room.
 */
export function setupNotificationHandler(getCurrentRoomId: () => string | null) {
  Notifications.setNotificationHandler({
    handleNotification: async (notification) => {
      const data = notification.request.content.data;
      const currentRoom = getCurrentRoomId();

      // Suppress if user is viewing the same room
      const shouldShow = data.room_id !== currentRoom;

      return {
        shouldShowBanner: shouldShow,
        shouldShowList: shouldShow,
        shouldPlaySound: shouldShow,
        shouldSetBadge: true, // Always update badge
      };
    },
  });
}

/**
 * Handle notification tap (deep linking).
 * CONTEXT.md: Navigate to exact message, replace current view.
 */
export function setupNotificationResponseListener() {
  // Handle notification tap when app is running
  const subscription = Notifications.addNotificationResponseReceivedListener(
    async (response) => {
      const data = response.notification.request.content.data as {
        room_id: string;
        thread_id: string;
        message_id: string;
      };

      if (data.room_id && data.message_id) {
        // CONTEXT.md: Navigation replaces current view
        router.replace({
          pathname: '/(app)/rooms/[roomId]',
          params: {
            roomId: data.room_id,
            threadId: data.thread_id,
            scrollToMessage: data.message_id,
          },
        });
      }
    }
  );

  return subscription;
}

/**
 * Handle cold start from notification.
 * Must check for initial notification on app launch.
 */
export async function handleInitialNotification() {
  const response = await Notifications.getLastNotificationResponseAsync();

  if (response) {
    const data = response.notification.request.content.data as {
      room_id: string;
      thread_id: string;
      message_id: string;
    };

    if (data.room_id && data.message_id) {
      // Small delay to ensure navigation is ready
      setTimeout(() => {
        router.replace({
          pathname: '/(app)/rooms/[roomId]',
          params: {
            roomId: data.room_id,
            threadId: data.thread_id,
            scrollToMessage: data.message_id,
          },
        });
      }, 300);
    }
  }
}
```

### Pattern 3: Android Notification Channels

**What:** Configure notification channels for Android 8.0+
**When to use:** App initialization, before any notifications

```typescript
// Source: Expo docs + CONTEXT.md decisions
// services/notifications/index.ts
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

// CONTEXT.md: Custom sound for Dialectic
// CONTEXT.md: Distinct sound for Claude (LLM) messages vs human messages
const HUMAN_SOUND = 'human_notification.wav';
const LLM_SOUND = 'llm_notification.wav';

export async function setupNotificationChannels() {
  if (Platform.OS !== 'android') return;

  // Human messages channel
  await Notifications.setNotificationChannelAsync('human_messages', {
    name: 'Messages from Humans',
    importance: Notifications.AndroidImportance.HIGH,
    sound: HUMAN_SOUND,
    vibrationPattern: [0, 250, 250, 250],
    lightColor: '#3b82f6',
  });

  // LLM messages channel (distinct sound per CONTEXT.md)
  await Notifications.setNotificationChannelAsync('llm_messages', {
    name: 'Messages from Claude',
    importance: Notifications.AndroidImportance.HIGH,
    sound: LLM_SOUND,
    vibrationPattern: [0, 100, 100, 100, 100, 100],
    lightColor: '#8b5cf6',
  });

  // Room-specific channels created dynamically when user joins
}

/**
 * Create a notification channel for a specific room.
 * Allows per-room mute via CONTEXT.md requirement.
 */
export async function createRoomChannel(roomId: string, roomName: string) {
  if (Platform.OS !== 'android') return;

  await Notifications.setNotificationChannelAsync(`room_${roomId}`, {
    name: `${roomName} Notifications`,
    importance: Notifications.AndroidImportance.HIGH,
    sound: HUMAN_SOUND,
    groupId: 'rooms',
  });
}
```

### Pattern 4: Backend Push Service

**What:** Send push notifications from FastAPI backend
**When to use:** When message is created and recipient is backgrounded

```python
# Source: exponent-server-sdk-python docs + CONTEXT.md decisions
# api/notifications/service.py
from exponent_server_sdk import (
    DeviceNotRegisteredError,
    PushClient,
    PushMessage,
    PushServerError,
    PushTicketError,
)
from typing import List, Optional
import logging
import os

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
        badge_counts: dict[str, int] = None,
    ) -> dict:
        """
        Send push notification for a new message.

        Args:
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
               WHERE user_id = ANY($1) AND is_active = true""",
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


# Singleton instance
push_service = PushNotificationService()
```

### Pattern 5: Badge Count Calculation

**What:** Calculate and update badge counts server-side
**When to use:** With each push notification, on read receipt

```python
# Source: CONTEXT.md decisions
# api/notifications/service.py (additional method)

async def calculate_badge_count(db, user_id: str) -> int:
    """
    CONTEXT.md: Badge count = number of rooms with unread messages.
    Not total message count.
    """
    # Get rooms with messages newer than user's last read
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
```

### Pattern 6: Foreground Suppression

**What:** Don't send push if user is actively in the room
**When to use:** Before sending push notification

```python
# transport/handlers.py extension

async def _should_send_push(
    self,
    user_id: UUID,
    room_id: UUID,
) -> bool:
    """
    Check if user should receive push notification.
    Returns False if user is actively connected to the room.
    """
    # Check if user has active WebSocket connection to this room
    active_connections = self.connections.get_user_connections(user_id, room_id)
    if active_connections:
        # User is foregrounded in this room
        return False

    # Check user's presence status
    presence = await self.db.fetchrow(
        "SELECT status FROM user_presence WHERE user_id = $1 AND room_id = $2",
        user_id, room_id
    )

    # Only send push if user is offline or away (not online)
    return presence is None or presence['status'] != 'online'
```

### Anti-Patterns to Avoid

- **Sending push to foreground users:** Always check WebSocket connection status before sending push
- **Badge count in notification only:** Badge must also be set client-side on foreground notification
- **Single token per user:** Users have multiple devices; store token per user+device pair
- **Ignoring DeviceNotRegisteredError:** Must mark tokens inactive to avoid wasted sends
- **Testing in Expo Go:** SDK 54 requires development builds for push notifications
- **Hardcoding projectId:** Must read from Constants.expoConfig or Constants.easConfig
- **Synchronous push in WebSocket handler:** Use background task to avoid blocking message delivery

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Push API client | HTTP client wrapper | `exponent-server-sdk` | Handles batching, retries, error types |
| Token validation | Regex matching | `expo-device` checks | Device type detection is complex |
| Notification grouping | Custom logic | Platform thread_id | FCM/APNs handle natively |
| Badge management | Client-only | Server-calculated badge | Reliable across app states |
| Deep linking | Custom URL parsing | expo-router | Integrated with navigation |
| Permission handling | Native modules | expo-notifications | Cross-platform unified API |

**Key insight:** Push notification delivery has many edge cases (token expiry, rate limits, device unregistration). The Expo SDK and server SDKs handle these; custom solutions miss them.

## Common Pitfalls

### Pitfall 1: Testing in Expo Go

**What goes wrong:** Push notifications don't arrive in development
**Why it happens:** Expo SDK 54 removed push support from Expo Go
**How to avoid:**
- Use `npx eas build --profile development` for dev builds
- Test on physical devices only (emulators don't support push)
- Use Expo's push notification testing tool for quick tests
**Warning signs:** `getExpoPushTokenAsync` returns null or throws

### Pitfall 2: Missing projectId

**What goes wrong:** Token generation fails with "Missing projectId" error
**Why it happens:** projectId not configured in app.config.ts or not published to EAS
**How to avoid:**
- Run `npx eas-cli build:configure` to set up EAS project
- Ensure `extra.eas.projectId` is in app.config.ts
- Use `Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId`
**Warning signs:** Token generation throws, projectId is undefined

### Pitfall 3: Stale Push Tokens

**What goes wrong:** Notifications fail silently, DeviceNotRegistered errors
**Why it happens:** Tokens expire after app reinstall, long inactivity (~270 days)
**How to avoid:**
- Re-register token on every app launch
- Handle DeviceNotRegisteredError by marking token inactive
- Implement token refresh listener: `addPushTokenListener`
- Monthly token refresh even if unchanged
**Warning signs:** Increasing DeviceNotRegistered errors, delivery rates dropping

### Pitfall 4: Badge Count Drift

**What goes wrong:** Badge shows wrong count, doesn't clear on read
**Why it happens:** Client and server badge counts desync
**How to avoid:**
- Calculate badge server-side with every push
- Send badge in notification payload
- Update badge client-side on read receipt
- CONTEXT.md: Badge decreases when message scrolls into view (not on room open)
**Warning signs:** Badge shows messages already read, count higher than actual

### Pitfall 5: Cold Start Navigation Failure

**What goes wrong:** Tapping notification opens app but doesn't navigate
**Why it happens:** Navigation not ready when initial notification processed
**How to avoid:**
- Use `Notifications.getLastNotificationResponseAsync()` on app launch
- Add small delay (300ms) before navigation
- Handle in root layout after navigation mounts
- Check if router is ready before navigating
**Warning signs:** App opens to home screen instead of target message

### Pitfall 6: Notification Flood

**What goes wrong:** User receives dozens of notifications in quick succession
**Why it happens:** No grouping/stacking, push sent for every message
**How to avoid:**
- Use `thread_id` in notification for iOS grouping
- Use Android notification channels with group
- CONTEXT.md: Multiple messages group/stack per room
- Consider debouncing multiple messages in short window
**Warning signs:** User complaints, unsubscribes

### Pitfall 7: Android Sound Configuration Mismatch

**What goes wrong:** Custom sound doesn't play on Android
**Why it happens:** Sound must be configured on both notification AND channel
**How to avoid:**
- Configure sound in `setNotificationChannelAsync`
- Also include sound in notification content
- Use filename only (not path) when referencing sound
- Place .wav files in plugin sounds array
**Warning signs:** Default sound plays, custom sound ignored

## Code Examples

### App Config with Notifications Plugin

```typescript
// Source: Expo docs
// app.config.ts
export default {
  expo: {
    // ... existing config
    plugins: [
      // ... existing plugins
      [
        'expo-notifications',
        {
          icon: './assets/images/notification-icon.png',
          color: '#3b82f6',
          // CONTEXT.md: Custom sounds for Dialectic
          sounds: [
            './assets/sounds/human_notification.wav',
            './assets/sounds/llm_notification.wav',
          ],
        },
      ],
    ],
    ios: {
      // Required for SDK 54+
      entitlements: {
        'aps-environment': 'production',
      },
    },
  },
};
```

### Root Layout Notification Setup

```typescript
// Source: Expo docs + project patterns
// app/_layout.tsx (additions)
import { useEffect, useRef } from 'react';
import * as Notifications from 'expo-notifications';
import { useSession } from '@/contexts/session-context';
import {
  setupNotificationHandler,
  setupNotificationResponseListener,
  handleInitialNotification,
  setupNotificationChannels,
} from '@/services/notifications';
import { registerForPushNotifications } from '@/services/notifications/registration';
import { useWebSocketStore } from '@/stores/websocket-store';

function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { session } = useSession();
  const responseListener = useRef<Notifications.Subscription>();
  const { currentRoomId } = useWebSocketStore();

  useEffect(() => {
    // Setup notification channels (Android)
    setupNotificationChannels();

    // Setup foreground handler with room suppression
    setupNotificationHandler(() => currentRoomId);

    // Setup tap handler for deep linking
    responseListener.current = setupNotificationResponseListener();

    // Handle cold start notification
    handleInitialNotification();

    return () => {
      responseListener.current?.remove();
    };
  }, []);

  // Register for push when user is authenticated
  useEffect(() => {
    if (session?.user) {
      registerForPushNotifications(session.user.id);
    }
  }, [session?.user?.id]);

  return <>{children}</>;
}
```

### Database Schema for Push Tokens

```sql
-- Source: Best practices research
-- Add to dialectic/schema.sql

-- Push notification tokens (one per user+device)
CREATE TABLE push_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    expo_push_token TEXT NOT NULL,
    platform TEXT NOT NULL, -- 'ios' | 'android'
    device_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, expo_push_token)
);

CREATE INDEX idx_push_tokens_user ON push_tokens(user_id) WHERE is_active = true;
CREATE INDEX idx_push_tokens_token ON push_tokens(expo_push_token);

-- Room notification settings (mute per room)
CREATE TABLE room_notification_settings (
    user_id UUID NOT NULL REFERENCES users(id),
    room_id UUID NOT NULL REFERENCES rooms(id),
    muted BOOLEAN NOT NULL DEFAULT FALSE,
    muted_until TIMESTAMPTZ, -- Optional temporary mute
    PRIMARY KEY (user_id, room_id)
);
```

### Token Registration Endpoints

```python
# Source: REST API patterns
# api/notifications/routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import UUID
from typing import Optional

router = APIRouter(prefix="/notifications", tags=["notifications"])


class RegisterTokenRequest(BaseModel):
    expo_push_token: str
    platform: str  # 'ios' | 'android'
    device_name: Optional[str] = None


class MuteRoomRequest(BaseModel):
    room_id: UUID
    muted: bool
    muted_until: Optional[str] = None  # ISO timestamp


@router.post("/tokens")
async def register_push_token(
    request: RegisterTokenRequest,
    user_id: UUID = Depends(get_current_user),
    db = Depends(get_db),
):
    """Register or update a push token for the current user."""
    await db.execute(
        """
        INSERT INTO push_tokens (user_id, expo_push_token, platform, device_name, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (user_id, expo_push_token)
        DO UPDATE SET platform = $3, device_name = $4, is_active = true, updated_at = NOW()
        """,
        user_id, request.expo_push_token, request.platform, request.device_name
    )
    return {"status": "registered"}


@router.delete("/tokens")
async def unregister_push_token(
    expo_push_token: str,
    user_id: UUID = Depends(get_current_user),
    db = Depends(get_db),
):
    """Mark a push token as inactive."""
    await db.execute(
        """
        UPDATE push_tokens SET is_active = false, updated_at = NOW()
        WHERE user_id = $1 AND expo_push_token = $2
        """,
        user_id, expo_push_token
    )
    return {"status": "unregistered"}


@router.put("/rooms/{room_id}/mute")
async def update_room_mute(
    room_id: UUID,
    request: MuteRoomRequest,
    user_id: UUID = Depends(get_current_user),
    db = Depends(get_db),
):
    """Update mute settings for a room (CONTEXT.md: per-room mute option)."""
    await db.execute(
        """
        INSERT INTO room_notification_settings (user_id, room_id, muted, muted_until)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id, room_id)
        DO UPDATE SET muted = $3, muted_until = $4
        """,
        user_id, room_id, request.muted, request.muted_until
    )
    return {"status": "updated"}
```

### Message Handler Push Trigger

```python
# Source: Existing handlers.py pattern
# transport/handlers.py (extend _handle_send_message)

async def _handle_send_message(self, conn: Connection, payload: dict) -> None:
    """Handle new message from user."""
    # ... existing message creation code ...

    # After message is created and broadcast via WebSocket,
    # trigger push notifications for offline/away users
    await self._trigger_push_notifications(
        room_id=conn.room_id,
        thread_id=thread_id,
        message=message,
        sender_name=user_row['display_name'],
        sender_id=conn.user_id,
    )


async def _trigger_push_notifications(
    self,
    room_id: UUID,
    thread_id: UUID,
    message: Message,
    sender_name: str,
    sender_id: UUID,
) -> None:
    """Send push notifications to offline/away room members."""
    from api.notifications.service import push_service, calculate_badge_count

    # Get room members except sender
    members = await self.db.fetch(
        """
        SELECT rm.user_id FROM room_memberships rm
        LEFT JOIN room_notification_settings rns
            ON rm.user_id = rns.user_id AND rm.room_id = rns.room_id
        WHERE rm.room_id = $1
          AND rm.user_id != $2
          AND (rns.muted IS NULL OR rns.muted = false)
        """,
        room_id, sender_id
    )

    if not members:
        return

    # Filter to users who should receive push (not actively connected)
    recipients = []
    for member in members:
        if await self._should_send_push(member['user_id'], room_id):
            recipients.append(str(member['user_id']))

    if not recipients:
        return

    # Calculate badge counts for each recipient
    badge_counts = {}
    for user_id in recipients:
        badge_counts[user_id] = await calculate_badge_count(self.db, user_id)

    # Send push notifications
    is_llm = message.speaker_type.value in ('LLM_PRIMARY', 'LLM_PROVOKER')

    await push_service.send_message_notification(
        db=self.db,
        recipient_user_ids=recipients,
        room_id=str(room_id),
        thread_id=str(thread_id),
        message_id=str(message.id),
        sender_name=sender_name if not is_llm else "Claude",
        content=message.content,
        is_llm=is_llm,
        badge_counts=badge_counts,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FCM Legacy API | FCM v1 with OAuth | June 2024 | Must use service account key |
| Expo Go push testing | Development builds only | SDK 54 (2025) | Requires EAS Build for testing |
| Client-side badge | Server-calculated badge | Best practice | More reliable cross-state |
| Single sound | Multiple channels + sounds | Android 8.0 (2017) | Distinct sounds per message type |

**Deprecated/outdated:**
- FCM Legacy HTTP API: Deprecated June 2024, removed June 2025
- Push in Expo Go: Removed in SDK 54
- `getExpoPushTokenAsync()` without projectId: Throws in SDK 54

## Open Questions

1. **Notification grouping threshold**
   - What we know: Platform supports grouping via threadId/channelId
   - What's unclear: Optimal timing before consolidating multiple messages
   - Recommendation: Start with platform defaults, adjust based on user feedback

2. **Badge sync on multi-device**
   - What we know: CONTEXT.md says badge = rooms with unread
   - What's unclear: How to sync badge when message read on different device
   - Recommendation: Re-calculate badge on each push; client re-fetches on foreground

3. **LLM message sound choice**
   - What we know: CONTEXT.md says distinct sound for Claude messages
   - What's unclear: What the actual sound file should be
   - Recommendation: Claude's discretion - select a subtle, distinct tone (softer beep vs human chime)

4. **Deleted message handling for notification tap**
   - What we know: CONTEXT.md says "show toast then open room" if message deleted
   - What's unclear: How to detect message was deleted before navigation completes
   - Recommendation: Fetch message on navigation; if 404, show toast and stay in room

## Sources

### Primary (HIGH confidence)
- [Expo Notifications SDK Reference](https://docs.expo.dev/versions/latest/sdk/notifications/) - Complete API documentation
- [Expo Push Notifications Setup](https://docs.expo.dev/push-notifications/push-notifications-setup/) - Official setup guide
- [Expo Push Service API](https://docs.expo.dev/push-notifications/sending-notifications/) - Server-side sending
- [expo-server-sdk-python](https://github.com/expo-community/expo-server-sdk-python) - Official Python SDK

### Secondary (MEDIUM confidence)
- [FCM Token Management Best Practices](https://firebase.google.com/docs/cloud-messaging/manage-tokens) - Token lifecycle
- [Deep Linking with Expo Router](https://docs.expo.dev/linking/into-your-app/) - Navigation from notifications
- SDK 54 release notes - Push notification changes

### Tertiary (LOW confidence)
- WebSearch results for notification grouping patterns - Community approaches
- Medium articles on cold start handling - Implementation patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Expo APIs, well-documented
- Architecture patterns: HIGH - Based on official docs and existing codebase patterns
- Backend integration: HIGH - exponent-server-sdk is well-maintained
- Deep linking: MEDIUM - Some cold start edge cases need testing
- Custom sounds: MEDIUM - Configuration verified, actual behavior needs testing

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - Expo moves fast but core APIs stable)
