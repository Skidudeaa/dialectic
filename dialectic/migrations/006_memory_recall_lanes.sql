-- 006_memory_recall_lanes.sql — Three-lane recall + speaker attribution + supersession
--
-- ARCHITECTURE: Ports the verified findings of the July 2026 agent-memory
-- deep-research review (docs/research/agent-memory-2026-07/) into the memories
-- table: full-text + trigram lanes alongside the existing dense vector lane,
-- per-speaker attribution for three-way dialogue, and supersession metadata so
-- a restated fact replaces its predecessor instead of duplicating it.
--
-- WHY speaker_user_id: created_by_user_id records who SAVED a memory, not whose
-- statement it captures. LLM-extracted memories carry source_message_id, whose
-- message author is the actual speaker. Consigliere-grade recall needs
-- "Dan said X" to be queryable, so the speaker is denormalized here.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Speaker attribution
ALTER TABLE memories ADD COLUMN IF NOT EXISTS speaker_user_id UUID REFERENCES users(id);

UPDATE memories m
SET speaker_user_id = msg.user_id
FROM messages msg
WHERE m.source_message_id = msg.id
  AND m.speaker_user_id IS NULL
  AND msg.user_id IS NOT NULL;

UPDATE memories
SET speaker_user_id = created_by_user_id
WHERE speaker_user_id IS NULL
  AND created_by_user_id IS NOT NULL;

-- Supersession (validity windows: valid_from = created_at, valid_until = superseded_at)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by_memory_id UUID REFERENCES memories(id);

-- Full-text lane
ALTER TABLE memories ADD COLUMN IF NOT EXISTS fts TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(key, '') || ' ' || coalesce(content, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_memories_fts ON memories USING gin (fts);

-- Trigram lane (entity/restatement matching on key and content)
CREATE INDEX IF NOT EXISTS idx_memories_content_trgm ON memories USING gin (content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_key_trgm ON memories USING gin (key gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_memories_speaker ON memories(room_id, speaker_user_id);

COMMIT;
