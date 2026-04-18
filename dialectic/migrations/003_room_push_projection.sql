-- Trading snapshot push projection on rooms.
-- WHY: Observers (frontend, ops) need cheap "when did the bridge last push?"
--      and "how many pushes total?" without scanning the events table.
-- TRADEOFF: Two projection columns vs aggregating events on read — cheaper reads,
--           tiny write cost on every snapshot push.

ALTER TABLE rooms
    ADD COLUMN IF NOT EXISTS last_trading_push_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS trading_push_count   INTEGER NOT NULL DEFAULT 0;

-- Optional: backfill push_count from existing events for rooms that already
-- received pushes before this migration ran.
UPDATE rooms r
SET trading_push_count = sub.cnt,
    last_trading_push_at = sub.last_at
FROM (
    SELECT room_id,
           COUNT(*)         AS cnt,
           MAX(timestamp)   AS last_at
    FROM events
    WHERE event_type = 'trading_snapshot_received'
    GROUP BY room_id
) sub
WHERE r.id = sub.room_id;

-- Per-message JSONB metadata (origin tag, snapshot revision, etc.)
-- WHY: Replaces fragile content-LIKE matching for curator dedup. Lets us
--      filter by metadata->>'source' = 'trading_curator' deterministically.
-- TRADEOFF: One small JSONB column per message vs separate join table —
--           cheap and idiomatic for sparse tags.
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS metadata JSONB;

CREATE INDEX IF NOT EXISTS idx_messages_metadata_source
    ON messages ((metadata->>'source'));
