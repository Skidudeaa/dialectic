---
phase: 03-real-time-core
plan: 03
subsystem: real-time
tags: [zustand, presence, react-native, app-lifecycle, websocket]

# Dependency graph
requires:
  - phase: 03-01
    provides: WebSocket protocol with presence_update message type
  - phase: 03-02
    provides: websocketService.sendPresenceUpdate method
provides:
  - Presence store with online/away/offline state machine
  - usePresence hook with inactivity and lifecycle tracking
  - PresenceIndicator component for visual status display
  - App-level presence initialization
affects: [room-ui, participant-list, chat-interface]

# Tech tracking
tech-stack:
  added: []
  patterns: [zustand-presence-store, callback-based-app-lifecycle, app-root-provider-init]

key-files:
  created:
    - mobile/stores/presence-store.ts
    - mobile/hooks/use-presence.ts
    - mobile/components/ui/presence-indicator.tsx
  modified:
    - mobile/app/_layout.tsx

key-decisions:
  - "5-minute inactivity timeout for auto-away (per CONTEXT.md)"
  - "5-minute background timeout for offline transition"
  - "Manual away persists through activity (requires explicit setOnline)"
  - "PresenceProvider at app root ensures presence tracked from app launch"

patterns-established:
  - "Zustand store + hook pattern: Store for state, hook for behavior/side effects"
  - "Provider at app root for global initialization without rendering UI"

# Metrics
duration: 2min
completed: 2026-01-25
---

# Phase 3 Plan 3: Presence Tracking Summary

**Zustand presence store with 3-state machine (online/away/offline), inactivity timer, and app lifecycle integration**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-25T23:08:56Z
- **Completed:** 2026-01-25T23:11:18Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments
- Presence store tracks my status and other participants with manual away support
- usePresence hook integrates with existing callback-based useAppState for lifecycle transitions
- PresenceIndicator shows colored dot + text label with "last seen" for offline users
- App root _layout.tsx initializes presence tracking via PresenceProvider

## Task Commits

Each task was committed atomically:

1. **Task 1: Create presence store with state machine** - `b837141` (feat)
2. **Task 2: Create presence hook with inactivity timer** - `c2c1a4d` (feat)
3. **Task 3: Create presence indicator component** - `55f05cf` (feat)
4. **Task 4: Integrate presence tracking at app root** - `75a3752` (feat)

## Files Created/Modified
- `mobile/stores/presence-store.ts` - Zustand store with my status, manual away, and participants map
- `mobile/hooks/use-presence.ts` - Hook with 5-min inactivity timer and app lifecycle handling
- `mobile/components/ui/presence-indicator.tsx` - Visual indicator with dot + label, three sizes
- `mobile/app/_layout.tsx` - Added PresenceProvider wrapper for app-wide presence tracking

## Decisions Made
- 5-minute inactivity timeout triggers auto-away per CONTEXT.md specification
- 5-minute background timeout triggers offline (matches inactivity timeout)
- Manual away state persists through foregrounding (user must explicitly return online)
- PresenceProvider placed inside LockProvider so presence only tracked when user is authenticated

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Presence foundation complete for room UI integration
- PresenceIndicator ready for participant lists
- usePresence.touch() available for recording user activity on interactions
- updateParticipant() ready to receive presence broadcasts from WebSocket

---
*Phase: 03-real-time-core*
*Completed: 2026-01-25*
