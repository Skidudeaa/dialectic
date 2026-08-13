-- The room watchlist: what the wire (llm/wire.py) polls for breaking news.
-- v1 only needs the column to exist: NULL means the default watch — the
-- linked book's GDELT feed. Explicit entries ({type:"gdelt_book"|"url",
-- value}) are a later feature.

ALTER TABLE rooms ADD COLUMN IF NOT EXISTS watchlist JSONB DEFAULT NULL;

COMMENT ON COLUMN rooms.watchlist IS
    'Wire watchlist; NULL = default watch of the linked book GDELT feed';
