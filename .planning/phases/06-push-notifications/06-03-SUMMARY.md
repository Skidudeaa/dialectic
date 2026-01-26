---
phase: 06-push-notifications
plan: 03
subsystem: transport
tags: [push-notifications, websocket, fastapi, foreground-suppression]

# Dependency graph
requires:
  - phase: 06-push-notifications/01
    provides: PushNotificationService, push_service singleton, calculate_badge_count
  - phase: 03-real-time-core
    provides: ConnectionManager, MessageHandler, WebSocket infrastructure
provides:
  - Push notification integration in WebSocket message handler
  - Foreground suppression via connection and presence checks
  - Push trigger for human messages and LLM responses
affects: [06-04, 06-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [foreground suppression, lazy import for circular dependency avoidance]

key-files:
  created: []
  modified:
    - dialectic/transport/websocket.py
    - dialectic/transport/handlers.py

key-decisions:
  - "Foreground suppression checks both WebSocket connection AND presence status"
  - "Sentinel UUID (all zeros) used as sender_id for LLM messages to avoid self-exclusion"
  - "Push failures logged but don't block message delivery (fire and forget)"
  - "LLM streaming 'done' event triggers push with constructed Message object"

patterns-established:
  - "Lazy import of notification service inside method to avoid circular imports"
  - "Presence check as secondary suppression after connection check"

# Metrics
duration: 2min
completed: 2026-01-26
---

# Phase 6 Plan 3: WebSocket Handler Integration Summary

**Push notification triggers integrated into WebSocket message handler with foreground suppression for human and LLM messages**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-26T04:35:07Z
- **Completed:** 2026-01-26T04:36:54Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- ConnectionManager extended with get_user_connections method for foreground detection
- _should_send_push method checks connection AND presence status for suppression
- _trigger_push_notifications sends push to offline/away room members with badge counts
- Push triggered for human messages after WebSocket broadcast
- Push triggered for LLM streaming responses on "done" event
- Push triggered for LLM heuristic interjections after broadcast
- Mute settings respected via JOIN query with room_notification_settings

## Task Commits

Each task was committed atomically:

1. **Task 1: Add connection query method to ConnectionManager** - `76ab8aa` (feat)
2. **Task 2: Add push trigger methods to MessageHandler** - `499066c` (feat)
3. **Task 3: Call push trigger after message broadcast** - `551d422` (feat)

## Files Modified
- `dialectic/transport/websocket.py` - Added get_user_connections method
- `dialectic/transport/handlers.py` - Added _should_send_push, _trigger_push_notifications, and calls in message handlers

## Decisions Made
- **Foreground suppression strategy:** Check WebSocket connection first (fast, in-memory), then presence status (DB query) for edge cases
- **Sentinel UUID for LLM:** Use all-zeros UUID as sender_id to avoid matching any real user in exclusion queries
- **Constructed Message for streaming:** Create Message object from "done" event data for push trigger compatibility
- **Fire and forget:** Push failures logged but don't propagate exceptions to message delivery path

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - this plan extends existing backend infrastructure without external dependencies.

## Next Phase Readiness
- WebSocket handler integration complete
- Ready for Plan 04 (deep linking from notifications)
- Ready for Plan 05 (notification settings UI)

---
*Phase: 06-push-notifications*
*Completed: 2026-01-26*
