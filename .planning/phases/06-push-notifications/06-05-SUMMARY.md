---
phase: 06-push-notifications
plan: 05
subsystem: notifications
tags: [expo-notifications, zustand, mmkv, badge, visibility-tracking]

# Dependency graph
requires:
  - phase: 06-03
    provides: Push delivery with sender exclusion
  - phase: 06-04
    provides: Mobile notification handlers and deep linking
provides:
  - Notification store for badge counts and per-room unread tracking
  - Badge service for app icon updates
  - Message visibility hook for scroll-based read receipts
affects: [room-list-ui, message-list-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - MMKV-backed Zustand store for notification state
    - Visibility-based read tracking with FlashList integration

key-files:
  created:
    - mobile/stores/notification-store.ts
    - mobile/services/notifications/badge.ts
    - mobile/hooks/use-message-visibility.ts
  modified:
    - mobile/contexts/notification-context.tsx

key-decisions:
  - "seenMessageIds not persisted (session-based for scroll detection)"
  - "50% visible for 500ms counts as message 'seen'"
  - "Badge sync on app foreground via AppState listener"
  - "Backend needs GET /notifications/badge endpoint (noted for follow-up)"

patterns-established:
  - "Visibility-based read detection: 50% visible + 500ms = seen"
  - "Badge count = rooms with unread (not total messages)"

# Metrics
duration: 2min
completed: 2026-01-26
---

# Phase 6 Plan 5: Badge Management Summary

**MMKV-backed notification store with visibility-based badge decrement and foreground sync**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-26T04:39:20Z
- **Completed:** 2026-01-26T04:41:42Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Notification store tracks total unread rooms and per-room counts
- Badge service updates app icon badge count via expo-notifications
- Message visibility tracking marks messages as seen when 50%+ visible for 500ms
- Badge syncs when app comes to foreground

## Task Commits

Each task was committed atomically:

1. **Task 1: Notification store for badge state** - `37a3da6` (feat)
2. **Task 2: Badge service for app icon updates** - `9a4c0d9` (feat)
3. **Task 3: Message visibility tracking for badge decrement** - `ea4bf04` (feat)

## Files Created/Modified
- `mobile/stores/notification-store.ts` - Zustand store with MMKV for badge counts
- `mobile/services/notifications/badge.ts` - Badge update functions (updateBadge, clearBadge, syncBadgeFromStore, fetchAndSyncBadge)
- `mobile/hooks/use-message-visibility.ts` - Hook for scroll-based read detection
- `mobile/contexts/notification-context.tsx` - Added AppState listener for foreground badge sync

## Decisions Made
- seenMessageIds is session-based (not persisted) to handle scroll-into-view detection
- 50% visible for 500ms counts as message "seen" per FlashList viewability config
- Own messages skipped (no self-badge decrement)
- Badge sync triggered on AppState 'active' (app foreground)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Backend Follow-up Required

The `fetchAndSyncBadge` function expects a backend endpoint:
- **Endpoint:** `GET /notifications/badge`
- **Response:** `{ total_unread_rooms: number, room_counts: Record<string, number> }`
- **Purpose:** Multi-device badge sync on app foreground

This can be added to the Dialectic backend in a future enhancement.

## Next Phase Readiness

Phase 06 (Push Notifications) is now complete:
- 06-01: Push server infrastructure
- 06-02: Mobile notification setup
- 06-03: Push delivery with sender exclusion
- 06-04: Mobile notification handlers
- 06-05: Badge management (this plan)

Ready to proceed to Phase 07.

---
*Phase: 06-push-notifications*
*Completed: 2026-01-26*
