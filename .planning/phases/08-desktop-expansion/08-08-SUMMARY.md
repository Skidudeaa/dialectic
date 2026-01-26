---
phase: 08-desktop-expansion
plan: 08
subsystem: desktop
tags: [react-native, desktop-layout, flashlist-fallback, window-persistence, chat-ui]

# Dependency graph
requires:
  - phase: 08-05
    provides: macOS platform services and MenuBar component
  - phase: 08-06
    provides: Windows platform services and SystemTray component
provides:
  - DesktopLayout component for centered max-width content
  - ChatLayout wrapper for chat-specific desktop styling
  - PlatformMessageList with FlashList/FlatList fallback
  - useWindowPersistence hook for window state persistence
  - Desktop style utilities (DESKTOP constants, withDesktopStyles helper)
  - Full chat UI integration in macOS and Windows App.tsx
affects: [desktop-testing, shared-code-integration, future-mobile-extraction]

# Tech tracking
tech-stack:
  added: []
  patterns: [platform-aware list component, conditional FlashList import, window state persistence]

key-files:
  created:
    - packages/app/src/styles/desktop.ts
    - packages/app/src/components/desktop/DesktopLayout.tsx
    - packages/app/src/components/chat/PlatformMessageList.tsx
    - packages/app/src/components/chat/index.ts
    - packages/app/src/hooks/useWindowPersistence.ts
    - packages/app/src/hooks/index.ts
  modified:
    - packages/app/src/components/desktop/index.ts
    - packages/app/src/index.ts
    - packages/macos/App.tsx
    - packages/windows/App.tsx

key-decisions:
  - "FlashList on mobile only: Desktop uses FlatList fallback for react-native-macos/windows compatibility"
  - "Conditional FlashList import: try/catch prevents crash if native module unavailable"
  - "MMKV for window state: Uses dialectic-window storage ID for window persistence"
  - "500ms debounce for window saves: Prevents excessive writes during resize"
  - "Platform-specific border radius: macOS uses rounded (12px), Windows uses sharper (8px)"
  - "Placeholder MessageBubble in App.tsx: Mobile components to be extracted to @dialectic/app later"

patterns-established:
  - "Platform list abstraction: PlatformMessageList checks Platform.OS and uses appropriate implementation"
  - "Desktop layout centering: DesktopLayout with maxWidth prop centers content on wide screens"
  - "Window persistence: useWindowPersistence saves/restores via MMKV (actual resize needs native module)"

# Metrics
duration: 3min
completed: 2026-01-26
---

# Phase 8 Plan 8: Desktop Visual Polish Summary

**Desktop layout centering, platform-aware message list with FlashList/FlatList fallback, and chat UI wired into macOS/Windows apps**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-26T00:57:00Z
- **Completed:** 2026-01-26T01:00:00Z
- **Tasks:** 3
- **Files created:** 6
- **Files modified:** 4

## Accomplishments

- Created DesktopLayout and ChatLayout for centered max-width content on wide screens
- Created PlatformMessageList with FlashList (mobile) and FlatList (desktop) fallback
- Added useWindowPersistence hook for remembering window size/position
- Wired full chat UI into macOS and Windows App.tsx with all desktop features

## Task Commits

Each task was committed atomically:

1. **Task 1: Create desktop layout and centered content wrapper** - `ce12928` (feat)
2. **Task 2: Create platform-aware message list with FlashList/FlatList fallback** - `d0eef78` (feat)
3. **Task 3: Wire chat UI components into desktop App.tsx files** - `2d8b01e` (feat)

## Files Created/Modified

**Created:**
- `packages/app/src/styles/desktop.ts` - Desktop style constants (DESKTOP), utilities (withDesktopStyles), platform detection
- `packages/app/src/components/desktop/DesktopLayout.tsx` - DesktopLayout and ChatLayout for centered content
- `packages/app/src/components/chat/PlatformMessageList.tsx` - Cross-platform message list with FlashList/FlatList
- `packages/app/src/components/chat/index.ts` - Barrel export for chat components
- `packages/app/src/hooks/useWindowPersistence.ts` - Window state persistence hook
- `packages/app/src/hooks/index.ts` - Barrel export for hooks

**Modified:**
- `packages/app/src/components/desktop/index.ts` - Added DesktopLayout, ChatLayout exports
- `packages/app/src/index.ts` - Added chat, hooks, styles exports
- `packages/macos/App.tsx` - Full chat UI with ChatLayout, PlatformMessageList, CollapsibleSidebar
- `packages/windows/App.tsx` - Same chat UI with Windows-specific styling (sharper corners)

## Decisions Made

1. **FlashList conditional import:** try/catch around require prevents crash if native module not available on desktop platforms

2. **FlatList desktop optimizations:** windowSize=10, maxToRenderPerBatch=10, updateCellsBatchingPeriod=50 for smooth scrolling

3. **Platform-specific border radius:** macOS uses 12px (rounded), Windows uses 8px (sharper) per platform conventions

4. **MMKV separate storage:** Window persistence uses dedicated MMKV instance (id: dialectic-window) to isolate from other storage

5. **Placeholder MessageBubble:** Desktop apps define local MessageBubble component - mobile UI components will be extracted to @dialectic/app in future plan

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- [x] DesktopLayout centers content with max-width on wide screens
- [x] desktopStyles provides consistent styling utilities
- [x] PlatformMessageList uses FlashList on mobile, FlatList on desktop
- [x] useWindowPersistence saves/restores window dimensions
- [x] macOS App.tsx renders message list with ChatLayout wrapper
- [x] Windows App.tsx renders message list with ChatLayout wrapper
- [x] All desktop features exported from @dialectic/app

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Desktop visual polish complete with centered layouts and message lists
- Both macOS and Windows apps render actual chat UI (with placeholder data)
- Ready for shared code extraction (mobile components to @dialectic/app)
- Window persistence hook ready - native module needed for actual window resize
- Chat UI integration pattern established for both desktop platforms

---
*Phase: 08-desktop-expansion*
*Completed: 2026-01-26*
