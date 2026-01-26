---
phase: 07-dialectic-differentiators
plan: 05
subsystem: ui
tags: [react-native, websocket, llm, streaming, zustand]

# Dependency graph
requires:
  - phase: 07-01
    provides: LLM interjection backend with speaker_type and interjection_type
  - phase: 07-04
    provides: LLM settings store with heuristics configuration
provides:
  - Interjection UX with unprompted badge
  - Provoker persona styling (amber colors, asterisk)
  - Stop button for active LLM streams
  - WebSocket cancel_llm and llm_cancelled event types
affects: [phase-8-desktop, llm-features]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "speakerType and interjectionType metadata in LLM payload"
    - "cancelStream action sends WebSocket message + clears state"
    - "ListFooterComponent for thinking bubble when last message is human"

key-files:
  created: []
  modified:
    - mobile/services/websocket/types.ts
    - mobile/stores/llm-store.ts
    - mobile/hooks/use-llm.ts
    - mobile/components/ui/llm-message-bubble.tsx
    - mobile/components/chat/message-list.tsx

key-decisions:
  - "Support both lowercase and uppercase speakerType values for flexibility"
  - "Provoker uses amber color scheme (#f59e0b) vs indigo for primary"
  - "Stop button is red-500 for prominence during streaming"

patterns-established:
  - "Interjection metadata flows: server -> llm_done payload -> store -> useLLM hook -> component props"
  - "Cancel pattern: cancel action -> cancelStream -> WebSocket message + immediate state clear"

# Metrics
duration: 4min
completed: 2026-01-26
---

# Phase 7 Plan 5: LLM Interjection UX Summary

**Visual distinction for proactive interjections with unprompted badge, provoker persona styling (amber), and stop button for canceling active LLM streams**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-26T05:41:00Z
- **Completed:** 2026-01-26T05:44:56Z
- **Tasks:** 5
- **Files modified:** 5

## Accomplishments
- Extended WebSocket types with speaker_type, interjection_type, and llm_cancelled event
- Added interjection metadata tracking to LLM store with cancelStream action
- Updated useLLM hook to expose cancel and interjection metadata
- Enhanced LLMMessageBubble with unprompted badge and provoker styling
- Wired stop button in message list to cancel active streams

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend WebSocket types for interjection metadata** - `86dd5b7` (feat)
2. **Task 2: Update LLM store with cancel and interjection state** - `a387ecb` (feat)
3. **Task 3: Update useLLM hook to expose cancel and metadata** - `e57d110` (feat)
4. **Task 4: Enhance LLM message bubble with interjection UI** - `fb032ad` (feat)
5. **Task 5: Wire up stop button in message list** - `8013c29` (feat)

## Files Created/Modified
- `mobile/services/websocket/types.ts` - Added llm_cancelled, speaker_type, interjection_type to types
- `mobile/stores/llm-store.ts` - Added interjection metadata state and cancelStream action
- `mobile/hooks/use-llm.ts` - Exposed cancel and interjection metadata, handles llm_cancelled
- `mobile/components/ui/llm-message-bubble.tsx` - Unprompted badge, provoker styling, stop button
- `mobile/components/chat/message-list.tsx` - Wired useLLM hook for cancel and metadata

## Decisions Made
- **Support both case variants:** speakerType accepts both 'llm_primary' and 'LLM_PRIMARY' for flexibility between WebSocket payload (lowercase) and Message store (uppercase)
- **Amber for provoker:** Provoker mode uses amber (#f59e0b) color scheme to distinguish from primary indigo (#6366f1)
- **Prominent stop button:** Stop button uses red-500 with white text (vs previous red-100/red-600) for better visibility during streaming

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed without issues.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- LLM interjection UX complete with visual indicators and cancel capability
- Phase 7 (Dialectic Differentiators) complete - all 5 plans executed
- Ready for Phase 8 (Desktop) or backend integration testing

---
*Phase: 07-dialectic-differentiators*
*Completed: 2026-01-26*
