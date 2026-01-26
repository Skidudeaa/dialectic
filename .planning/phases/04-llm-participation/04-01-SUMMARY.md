---
phase: 04-llm-participation
plan: 01
subsystem: llm
tags: [websocket, streaming, context-assembly, tiktoken]

# Dependency graph
requires:
  - phase: 03-real-time-core
    provides: WebSocket transport layer with message routing
provides:
  - LLM streaming message types (SUMMON_LLM, CANCEL_LLM, LLM_DONE, LLM_ERROR)
  - Context assembly module with smart truncation
  - stream_response async generator for token-by-token delivery
  - summon_llm and cancel_llm WebSocket handlers
affects:
  - 04-02-mobile-streaming (will consume streaming events)
  - 04-03-response-display (will render streamed content)

# Tech tracking
tech-stack:
  added: [tiktoken]
  patterns: [async-generator-streaming, priority-based-truncation]

key-files:
  created:
    - dialectic/llm/context.py
  modified:
    - dialectic/transport/websocket.py
    - dialectic/llm/orchestrator.py
    - dialectic/transport/handlers.py

key-decisions:
  - "100k token context window with 4k reserved for output"
  - "Priority scoring: recency (80-100pts) > @Claude mentions (80pts) > LLM responses (60pts) > questions (20pts)"
  - "Always include last 10 messages regardless of score"
  - "tiktoken with fallback to 4-char-per-token estimation"

patterns-established:
  - "Streaming protocol: thinking -> streaming(N) -> done|error"
  - "Context truncation via priority scoring before prompt building"

# Metrics
duration: 4min
completed: 2026-01-25
---

# Phase 4 Plan 01: Backend LLM Streaming Summary

**WebSocket streaming protocol with thinking/token/done events and smart context truncation prioritizing recent + @Claude messages**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-25T20:04:00Z
- **Completed:** 2026-01-25T20:08:00Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments
- Added 4 new message types for LLM streaming lifecycle (SUMMON_LLM, CANCEL_LLM, LLM_DONE, LLM_ERROR)
- Created context assembly module with priority-based truncation (prioritizes recent + @Claude + LLM responses)
- Implemented stream_response async generator yielding thinking/streaming/done/error events
- Added summon_llm handler for explicit @Claude invocation with real-time token streaming

## Task Commits

Each task was committed atomically:

1. **Task 1: Add LLM streaming message types** - `21102c8` (feat)
2. **Task 2: Create context assembly module** - `355718b` (feat)
3. **Task 3: Add streaming response method to orchestrator** - `ffb800e` (feat)
4. **Task 4: Add streaming and summon handlers** - `c2195fe` (feat)

## Files Created/Modified
- `dialectic/transport/websocket.py` - Added SUMMON_LLM, CANCEL_LLM, LLM_DONE, LLM_ERROR message types
- `dialectic/llm/context.py` - New module for priority-based context truncation with tiktoken
- `dialectic/llm/orchestrator.py` - Added stream_response async generator with assemble_context integration
- `dialectic/transport/handlers.py` - Added _handle_summon_llm and _handle_cancel_llm, updated _trigger_llm for streaming

## Decisions Made
- 100k token context window with 4k reserved for output (matches Claude 3 limits)
- Priority scoring system: recency gets highest weight (100pts for last 20%), @Claude mentions (80pts), LLM responses (60pts), questions (20pts)
- Always include last 10 messages regardless of priority score to maintain coherence
- tiktoken for accurate token counting with 4-char-per-token fallback when unavailable
- cancel_llm is minimal implementation (acknowledges request) - full cancellation requires asyncio task tracking (deferred)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Backend streaming infrastructure complete
- Mobile client can now receive llm_thinking, llm_streaming, llm_done, llm_error events
- Ready for Plan 02: Mobile streaming display components

---
*Phase: 04-llm-participation*
*Completed: 2026-01-25*
