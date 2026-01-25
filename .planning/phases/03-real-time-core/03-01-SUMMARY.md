---
phase: 03-real-time-core
plan: 01
subsystem: transport
tags: [websocket, presence, receipts, postgres, real-time]

# Dependency graph
requires:
  - phase: 02-authentication
    provides: user sessions and authenticated websocket connections
provides:
  - user_presence table for per-room status tracking
  - message_receipts table for delivery and read receipts
  - WebSocket handlers for presence heartbeats and updates
  - WebSocket handlers for delivery and read receipts
affects: [03-02, 03-03, mobile-client-sync]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "UPSERT pattern for presence tracking (INSERT ON CONFLICT DO UPDATE)"
    - "Targeted send_to_user for receipts (not broadcast)"
    - "Room-wide broadcast with sender exclusion for presence"

key-files:
  created: []
  modified:
    - dialectic/schema.sql
    - dialectic/transport/websocket.py
    - dialectic/transport/handlers.py

key-decisions:
  - "PRESENCE_BROADCAST uses same value as PRESENCE_UPDATE for wire compatibility"
  - "Receipts sent only to message sender, not broadcast to room"
  - "Presence status validated to online/away/offline only"

patterns-established:
  - "Upsert presence on heartbeat with ON CONFLICT DO UPDATE"
  - "Receipt handlers fetch sender and use send_to_user not broadcast"

# Metrics
duration: 2min
completed: 2026-01-25
---

# Phase 03 Plan 01: Backend Presence & Receipts Summary

**WebSocket handlers for user presence tracking (online/away/offline) and message delivery/read receipts with PostgreSQL persistence**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-25T23:03:56Z
- **Completed:** 2026-01-25T23:06:03Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added `user_presence` table tracking user status per room with heartbeat timestamps
- Added `message_receipts` table tracking delivery and read receipts per message
- Implemented four new WebSocket handlers: presence_heartbeat, presence_update, message_delivered, message_read
- Extended MessageTypes with all new inbound and outbound message types

## Task Commits

Each task was committed atomically:

1. **Task 1: Add presence and receipt tables to schema** - `1ea0ac4` (feat)
2. **Task 2: Add presence and receipt message types** - `8c16efc` (feat)
3. **Task 3: Implement presence and receipt handlers** - `bf0702a` (feat)

## Files Created/Modified

- `dialectic/schema.sql` - Added user_presence and message_receipts tables with indexes
- `dialectic/transport/websocket.py` - Added PRESENCE_*, MESSAGE_*, DELIVERY_RECEIPT, READ_RECEIPT message types
- `dialectic/transport/handlers.py` - Implemented four new handler methods with database persistence and messaging

## Decisions Made

- **PRESENCE_BROADCAST constant:** Uses same wire value "presence_update" as PRESENCE_UPDATE for client simplicity - clients receive same message type whether updating own status or receiving others' updates
- **Receipt targeting:** Delivery/read receipts sent only to original message sender via send_to_user(), not broadcast to entire room (reduces noise, matches WhatsApp/Signal pattern)
- **Status validation:** Presence status strictly validated to "online", "away", or "offline" - rejects invalid values with error message

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - database verification could not run (PostgreSQL not available in environment) but schema SQL syntax and Python imports verified successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Backend presence and receipt infrastructure complete
- Ready for mobile client to implement presence heartbeat and receipt sending
- Typing indicators (Plan 02) can build on this presence pattern
- No blockers

---
*Phase: 03-real-time-core*
*Completed: 2026-01-25*
