-- 004: Drop the dead `outbox` table.
--
-- WHY: `outbox` was created in 001 as the delivery queue for Dialectic
-- snapshot pushes, and the drainer that was supposed to consume it was
-- never written. Every row ever enqueued sat status='pending' forever —
-- 58,769 of them by the time this ran, ~1 per fetch cycle per linked book
-- since April. Nothing has ever read the table.
--
-- Replaying that backlog would be actively wrong: each row is a snapshot
-- of a market that has since moved, and Dialectic upserts the room's
-- thesis_state_current memory on every receipt, so a drain would walk the
-- room backwards through four months of stale state.
--
-- Delivery is now inline from the coordinator (web/runtime/dialectic_push.py)
-- and failures spool to the FILE outbox at snapshots/outbox/, which has a
-- replay path and an operator UI behind /api/bridge/outbox.
--
-- NOTE: no VACUUM here. Reclaiming the freed pages needs the service stopped;
-- the deploy orchestrator does that separately.

DROP INDEX IF EXISTS idx_outbox_pending;
DROP TABLE IF EXISTS outbox;
