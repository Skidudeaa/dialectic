---
phase: 06-push-notifications
plan: 01
subsystem: api
tags: [expo, push-notifications, fastapi, postgresql, badge]

# Dependency graph
requires:
  - phase: 02-authentication
    provides: user authentication, JWT tokens, get_current_user dependency
  - phase: 03-real-time-core
    provides: message_receipts table, room_memberships, WebSocket infrastructure
provides:
  - Push token storage per user-device pair
  - PushNotificationService with Expo Push API integration
  - Badge calculation (rooms with unread, not message count)
  - REST endpoints for token registration and room mute
affects: [06-02, 06-03, 06-04]

# Tech tracking
tech-stack:
  added: [exponent-server-sdk>=2.0.0]
  patterns: [singleton push service, badge as room count, per-room mute settings]

key-files:
  created:
    - dialectic/api/notifications/__init__.py
    - dialectic/api/notifications/schemas.py
    - dialectic/api/notifications/service.py
    - dialectic/api/notifications/routes.py
  modified:
    - dialectic/schema.sql
    - dialectic/api/main.py
    - dialectic/requirements.txt

key-decisions:
  - "Badge count = rooms with unread messages (not total message count)"
  - "LLM messages use robot emoji prefix in notification title"
  - "Distinct sounds: human_notification.wav vs llm_notification.wav"
  - "DeviceNotRegisteredError marks tokens inactive (not deleted)"

patterns-established:
  - "Lazy-init PushClient: Client created on first use with optional auth token"
  - "Token upsert pattern: INSERT ... ON CONFLICT DO UPDATE for re-registration"
  - "Room mute settings: Separate table with optional muted_until for temporary mute"

# Metrics
duration: 5min
completed: 2026-01-26
---

# Phase 6 Plan 1: Backend Infrastructure Summary

**Push notification backend with Expo SDK, token storage, badge calculation, and REST endpoints for token/mute management**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-26T04:27:53Z
- **Completed:** 2026-01-26T04:33:00Z
- **Tasks:** 4
- **Files modified:** 7

## Accomplishments
- Push token storage with user_id + expo_push_token unique constraint
- PushNotificationService with Expo Push API integration and error handling
- Badge calculation based on rooms with unread messages (per CONTEXT.md)
- REST endpoints: token registration, unregistration, room mute, badge retrieval

## Task Commits

Each task was committed atomically:

1. **Task 1: Database schema for push tokens** - `fe49f23` (feat)
2. **Task 2: Push notification service with Expo SDK** - `0f4ed7a` (feat)
3. **Task 3: Token registration REST endpoints** - `dfaf0cf` (feat)
4. **Task 4: Badge count endpoint** - (included in Task 3, already in routes.py)

## Files Created/Modified
- `dialectic/schema.sql` - Added push_tokens and room_notification_settings tables
- `dialectic/requirements.txt` - Added exponent-server-sdk>=2.0.0
- `dialectic/api/notifications/__init__.py` - Module exports
- `dialectic/api/notifications/schemas.py` - Pydantic models for token/badge requests
- `dialectic/api/notifications/service.py` - PushNotificationService with send_message_notification
- `dialectic/api/notifications/routes.py` - REST endpoints for tokens, mute, badge
- `dialectic/api/main.py` - Include notifications router

## Decisions Made
- Badge count = distinct rooms with unread, not total message count (per CONTEXT.md)
- LLM messages get robot emoji prefix in title (per CONTEXT.md)
- Distinct sounds configured via channel_id: llm_messages vs human_messages
- DeviceNotRegisteredError marks tokens inactive rather than deleting them

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- dialectic/ folder is a separate git repository (not tracked in parent DwoodAmo repo)
  - Resolution: Committed changes to dialectic repo directly
- Missing pip dependencies required installation (pyjwt, pwdlib, asyncpg)
  - Resolution: Installed dependencies to verify imports

## User Setup Required

None - no external service configuration required for this plan.

## Next Phase Readiness
- Backend push infrastructure complete
- Ready for Plan 02 (mobile notification setup)
- Ready for Plan 03 (WebSocket push trigger integration)
- Ready for Plan 04 (deep linking from notifications)

---
*Phase: 06-push-notifications*
*Completed: 2026-01-26*
