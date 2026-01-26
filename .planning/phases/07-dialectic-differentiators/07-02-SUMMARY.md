---
phase: 07-dialectic-differentiators
plan: 02
subsystem: ui
tags: [react-native, fork, context-menu, hold-menu, gesture]

# Dependency graph
requires:
  - phase: 03-real-time-core
    provides: WebSocket connection and message infrastructure
provides:
  - Long-press context menu on messages with fork option
  - useForkThread hook for creating thread branches
  - MessageContextMenu component wrapping messages
affects: [07-03, 07-04]

# Tech tracking
tech-stack:
  added: [react-native-hold-menu, expo-clipboard]
  patterns: [HoldItem wrapper, fork mutation hook]

key-files:
  created:
    - mobile/hooks/use-fork.ts
    - mobile/components/chat/message-context-menu.tsx
  modified:
    - mobile/app/_layout.tsx
    - mobile/components/chat/message-list.tsx
    - mobile/package.json

key-decisions:
  - "HoldMenuProvider wrapped inside SafeAreaProvider for insets access"
  - "GestureHandlerRootView at root for proper gesture handling"
  - "Android skips naming prompt (Alert.prompt iOS-only), uses auto-generated title"
  - "Simple useState pattern for fork mutation (no react-query dependency)"

patterns-established:
  - "HoldItem wrapper pattern for long-press context menus"
  - "Type assertion for dynamic routes not yet defined in expo-router"

# Metrics
duration: 4min
completed: 2026-01-26
---

# Phase 7 Plan 2: Mobile Fork Infrastructure Summary

**Long-press context menu with fork-from-here option using react-native-hold-menu, enabling thread branching from any message**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-26T05:29:24Z
- **Completed:** 2026-01-26T05:33:22Z
- **Tasks:** 4
- **Files modified:** 5

## Accomplishments
- Installed react-native-hold-menu with HoldMenuProvider at app root
- Created useForkThread hook for POST /threads/{id}/fork API call
- Built MessageContextMenu component with fork and copy options
- Integrated context menu into message list for all message types

## Task Commits

Each task was committed atomically:

1. **Task 1: Install react-native-hold-menu** - `4b4ac1f` (feat)
2. **Task 2: Create fork thread hook** - `eb29d0c` (feat)
3. **Task 3: Create message context menu component** - `9d8f5c8` (feat)
4. **Task 4: Integrate context menu into message list** - `91bd418` (feat)

## Files Created/Modified
- `mobile/hooks/use-fork.ts` - Fork thread mutation hook with navigation
- `mobile/components/chat/message-context-menu.tsx` - Long-press menu wrapper
- `mobile/app/_layout.tsx` - Added HoldMenuProvider, GestureHandlerRootView, SafeAreaProvider
- `mobile/components/chat/message-list.tsx` - Wrapped messages with context menu, added roomId prop
- `mobile/package.json` - Added react-native-hold-menu and expo-clipboard

## Decisions Made
- Used SafeAreaProvider + custom HoldMenuWrapper to access insets (HoldMenuProvider requires safeAreaInsets prop)
- GestureHandlerRootView added at root for proper gesture support
- Android forks immediately with auto-generated title since Alert.prompt is iOS-only
- Used simple useState pattern for fork mutation to match existing codebase patterns (no react-query)
- Type assertion on router.push for dynamic routes not yet defined in expo-router type system

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- HoldMenuProvider requires ReactElement children, not ReactNode - fixed by updating type definition
- HoldMenuProvider requires safeAreaInsets prop - created HoldMenuWrapper component using useSafeAreaInsets

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Fork UI ready for testing once room/thread routes exist
- Backend fork endpoint required for full integration
- Cladogram visualization (07-03) can now reference fork navigation pattern

---
*Phase: 07-dialectic-differentiators*
*Completed: 2026-01-26*
