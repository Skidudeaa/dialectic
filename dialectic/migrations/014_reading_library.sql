-- The reading library: articles the room has actually read, kept whole.
-- The distilled summary also lands in `memories` (key 'reading:<domain>-<slug>',
-- dedup=False) so three-lane recall finds readings with zero recall changes;
-- the full body lives only here, where it cannot dwarf conversational memories.

CREATE TABLE IF NOT EXISTS reading_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    author TEXT,
    site TEXT,
    published TEXT,
    word_count INTEGER,
    content TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_claims JSONB NOT NULL DEFAULT '[]',
    source TEXT NOT NULL,
    source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    saved_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fts TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(title, '') || ' ' || summary || ' ' || content)
    ) STORED,
    UNIQUE (room_id, url)
);

CREATE INDEX IF NOT EXISTS idx_reading_items_fts ON reading_items USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_reading_items_room
    ON reading_items (room_id, created_at DESC);

COMMENT ON TABLE reading_items IS
    'Articles read by the room via the defuddle sidecar; source is proposal|night_shift|wire|deep_dive';
