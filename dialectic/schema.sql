-- schema.sql — PostgreSQL DDL

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Event log: append-only source of truth
CREATE TABLE events (
    id UUID PRIMARY KEY,
    sequence BIGSERIAL UNIQUE NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,
    room_id UUID,
    thread_id UUID,
    user_id UUID,
    payload JSONB NOT NULL
);

CREATE INDEX idx_events_room ON events(room_id, sequence);
CREATE INDEX idx_events_thread ON events(thread_id, sequence);
CREATE INDEX idx_events_type ON events(event_type);

-- Rooms
CREATE TABLE rooms (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    token TEXT UNIQUE NOT NULL,
    name TEXT,
    global_ontology TEXT,
    global_rules TEXT,
    primary_provider TEXT NOT NULL DEFAULT 'anthropic',
    fallback_provider TEXT NOT NULL DEFAULT 'openai',
    primary_model TEXT NOT NULL DEFAULT 'claude-sonnet-4-20250514',
    provoker_model TEXT NOT NULL DEFAULT 'claude-haiku-4-20250514',
    auto_interjection_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    interjection_turn_threshold INT NOT NULL DEFAULT 4,
    semantic_novelty_threshold FLOAT NOT NULL DEFAULT 0.7
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    display_name TEXT NOT NULL,
    style_modifier TEXT,
    aggression_level FLOAT NOT NULL DEFAULT 0.5,
    metaphysics_tolerance FLOAT NOT NULL DEFAULT 0.5,
    custom_instructions TEXT
);

-- Room memberships
CREATE TABLE room_memberships (
    room_id UUID NOT NULL REFERENCES rooms(id),
    user_id UUID NOT NULL REFERENCES users(id),
    joined_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (room_id, user_id)
);

-- Threads
CREATE TABLE threads (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    created_at TIMESTAMPTZ NOT NULL,
    parent_thread_id UUID REFERENCES threads(id),
    fork_point_message_id UUID,
    fork_memory_version INT,
    title TEXT
);

CREATE INDEX idx_threads_room ON threads(room_id);
CREATE INDEX idx_threads_parent ON threads(parent_thread_id);

-- Messages
CREATE TABLE messages (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES threads(id),
    sequence INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    speaker_type TEXT NOT NULL,
    user_id UUID REFERENCES users(id),
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    references_message_id UUID REFERENCES messages(id),
    references_memory_id UUID,
    model_used TEXT,
    prompt_hash TEXT,
    token_count INT,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (thread_id, sequence)
);

CREATE INDEX idx_messages_thread ON messages(thread_id, sequence);

-- Memories
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INT NOT NULL DEFAULT 1,
    scope TEXT NOT NULL,
    owner_user_id UUID REFERENCES users(id),
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    source_message_id UUID REFERENCES messages(id),
    created_by_user_id UUID NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'active',
    invalidated_by_user_id UUID REFERENCES users(id),
    invalidated_at TIMESTAMPTZ,
    invalidation_reason TEXT,
    embedding VECTOR(1536)
);

CREATE INDEX idx_memories_room ON memories(room_id);
CREATE INDEX idx_memories_status ON memories(room_id, status);
CREATE INDEX idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops);

-- Memory version history
CREATE TABLE memory_versions (
    memory_id UUID NOT NULL REFERENCES memories(id),
    version INT NOT NULL,
    content TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by_user_id UUID NOT NULL REFERENCES users(id),
    PRIMARY KEY (memory_id, version)
);

-- ============================================================
-- AUTHENTICATION TABLES
-- ============================================================

-- User credentials (email/password authentication)
CREATE TABLE user_credentials (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    email TEXT UNIQUE NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_credentials_email ON user_credentials(email);

-- Verification codes (email verification, password reset)
CREATE TABLE verification_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    code TEXT NOT NULL,
    purpose TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

CREATE INDEX idx_verification_codes_user ON verification_codes(user_id);

-- User sessions (multi-device management, refresh tokens)
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    refresh_token_hash TEXT NOT NULL,
    device_info JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token ON user_sessions(refresh_token_hash);

-- User PINs (biometric fallback unlock)
CREATE TABLE user_pins (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    pin_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- REAL-TIME PRESENCE & RECEIPTS
-- ============================================================

-- User presence tracking per room
CREATE TABLE user_presence (
    user_id UUID NOT NULL REFERENCES users(id),
    room_id UUID NOT NULL REFERENCES rooms(id),
    status TEXT NOT NULL DEFAULT 'offline',
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, room_id)
);

CREATE INDEX idx_user_presence_room_status ON user_presence(room_id, status);

-- Message delivery and read receipts
CREATE TABLE message_receipts (
    message_id UUID NOT NULL REFERENCES messages(id),
    user_id UUID NOT NULL REFERENCES users(id),
    receipt_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (message_id, user_id, receipt_type)
);

CREATE INDEX idx_message_receipts_message ON message_receipts(message_id);

-- ============================================================
-- FULL-TEXT SEARCH
-- ============================================================

-- Add search vector column for full-text search
ALTER TABLE messages ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- GIN index for fast full-text search
CREATE INDEX IF NOT EXISTS idx_messages_search
ON messages USING GIN (search_vector);

-- Trigger to auto-update search vector on insert/update
CREATE OR REPLACE FUNCTION messages_search_trigger() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english', COALESCE(NEW.content, ''));
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER messages_search_update
  BEFORE INSERT OR UPDATE ON messages
  FOR EACH ROW EXECUTE FUNCTION messages_search_trigger();

-- Composite index for date range filtering
CREATE INDEX IF NOT EXISTS idx_messages_created_at
ON messages (thread_id, created_at DESC);

-- Backfill existing messages with search vectors
UPDATE messages SET search_vector = to_tsvector('english', COALESCE(content, ''))
WHERE search_vector IS NULL;

-- ============================================================
-- PUSH NOTIFICATIONS
-- ============================================================

-- Push notification tokens (one per user+device pair)
CREATE TABLE push_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    expo_push_token TEXT NOT NULL,
    platform TEXT NOT NULL, -- 'ios' | 'android'
    device_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, expo_push_token)
);

CREATE INDEX idx_push_tokens_user ON push_tokens(user_id) WHERE is_active = true;
CREATE INDEX idx_push_tokens_token ON push_tokens(expo_push_token);

-- Room notification settings (per-room mute per CONTEXT.md)
CREATE TABLE room_notification_settings (
    user_id UUID NOT NULL REFERENCES users(id),
    room_id UUID NOT NULL REFERENCES rooms(id),
    muted BOOLEAN NOT NULL DEFAULT FALSE,
    muted_until TIMESTAMPTZ, -- Optional temporary mute
    PRIMARY KEY (user_id, room_id)
);
