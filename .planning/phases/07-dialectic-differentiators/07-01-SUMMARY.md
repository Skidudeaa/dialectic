---
phase: 07-dialectic-differentiators
plan: 01
subsystem: backend-api
tags: [genealogy, settings, llm, websocket, recursive-cte]

dependency-graph:
  requires: [06-push-notifications]
  provides: [genealogy-endpoint, settings-endpoint, stream-cancellation]
  affects: [07-02, 07-03, 07-04]

tech-stack:
  added: []
  patterns: [recursive-cte, asyncio-task-tracking, class-level-state]

key-files:
  created: []
  modified:
    - dialectic/api/main.py
    - dialectic/transport/websocket.py
    - dialectic/transport/handlers.py

decisions:
  - key: recursive-cte-for-genealogy
    choice: PostgreSQL recursive CTE with depth tracking
    why: Single query fetches entire tree with depth, efficient for typical tree depths
  - key: class-level-stream-tracking
    choice: Class-level _active_streams dict in MessageHandler
    why: Persists across handler instances, allows cancel_llm to find active stream
  - key: settings-validation-ranges
    choice: interjection_turn_threshold 2-12, semantic_novelty_threshold 0.3-0.95
    why: Matches RESEARCH.md recommendations for usable ranges

metrics:
  duration: 4 min
  completed: 2026-01-26
---

# Phase 07 Plan 01: Backend Genealogy and Settings Endpoints Summary

Backend API surface for thread genealogy visualization, LLM heuristic configuration, and stream cancellation.

## What Was Built

### Task 1: Thread Genealogy Endpoint
- `GET /rooms/{room_id}/genealogy` returns nested tree of all threads in room
- Uses PostgreSQL recursive CTE with depth tracking (max_depth parameter, default 20)
- Tree built in Python from flat query result (O(n) iteration)
- Response includes: id, parent_thread_id, fork_point_message_id, title, message_count, created_at, depth, children[]
- ThreadNodeResponse model with self-reference and model_rebuild()

### Task 2: Room Settings Endpoints
- `GET /rooms/{room_id}/settings` returns current heuristic values
- `PATCH /rooms/{room_id}/settings` updates with validation:
  - interjection_turn_threshold: 2-12 (how many messages before Claude interjects)
  - semantic_novelty_threshold: 0.3-0.95 (how different a message must be to trigger)
  - auto_interjection_enabled: boolean
- Dynamic UPDATE query only touches provided fields
- Logs ROOM_SETTINGS_UPDATED event on change
- Returns updated settings after PATCH

### Task 3: Stream Cancellation Support
- Added `LLM_CANCELLED` message type to MessageTypes
- Class-level `_active_streams: dict[UUID, Task]` tracks active streaming tasks by thread_id
- `_handle_summon_llm` wraps streaming in asyncio.Task for cancellation
- Extracted `_stream_llm_response` helper for task wrapping
- Existing stream auto-cancelled when new summon starts on same thread
- `_handle_cancel_llm` now calls task.cancel() on active stream
- Broadcasts `llm_cancelled` event to all room clients

## Decisions Made

| Decision | Choice | Why |
|----------|--------|-----|
| Genealogy query approach | Recursive CTE | Single efficient query vs multiple round trips; rooms rarely exceed 10 depth levels |
| Tree building location | Python after query | Easier to implement than nested SQL; O(n) iteration is fast |
| Stream tracking scope | Class-level dict | Persists across MessageHandler instances created per-message; enables cancel from any handler |
| Settings validation | Hard limits in endpoint | Prevents invalid configurations; matches RESEARCH.md guidance on usable ranges |

## Deviations from Plan

None - plan executed exactly as written.

## Commits

| Hash | Message |
|------|---------|
| 314f965 | feat(07-01): add thread genealogy endpoint |
| 0f825dd | feat(07-01): add room settings GET/PATCH endpoints |
| 451bb0f | feat(07-01): add LLM stream cancellation support |

## Next Phase Readiness

- [x] Genealogy endpoint ready for mobile cladogram visualization (07-02)
- [x] Settings endpoints ready for mobile configuration UI (07-03)
- [x] Stream cancellation ready for mobile stop button (07-04)

No blockers. All backend surface for Phase 7 differentiators now available.
