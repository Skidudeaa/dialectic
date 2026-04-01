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
    primary_model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    provoker_model TEXT NOT NULL DEFAULT 'claude-haiku-4-5-20251001',
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
    created_by_user_id UUID REFERENCES users(id), -- NULL for LLM-authored memories (scope='llm')
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
    updated_by_user_id UUID REFERENCES users(id), -- NULL for LLM-authored memory versions
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

-- ============================================================
-- CROSS-SESSION MEMORY INFRASTRUCTURE
-- ============================================================
-- Enables memories to be referenced and shared across rooms/sessions.
-- Unlocks: Knowledge Graph, LLM Self-Memory, Persistent Identity, Dialectic Graph.

-- Memory references: citations of memories across rooms
CREATE TABLE IF NOT EXISTS memory_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    target_thread_id UUID REFERENCES threads(id) ON DELETE SET NULL,
    target_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    referenced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    referenced_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    referenced_by_llm BOOLEAN NOT NULL DEFAULT FALSE,
    citation_context TEXT,
    relevance_score FLOAT,
    UNIQUE (source_memory_id, target_message_id)
);

CREATE INDEX idx_memory_refs_source ON memory_references(source_memory_id);
CREATE INDEX idx_memory_refs_target_room ON memory_references(target_room_id);
CREATE INDEX idx_memory_refs_target_message ON memory_references(target_message_id);

-- User memory collections: organize memories across rooms
CREATE TABLE IF NOT EXISTS user_memory_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    auto_inject BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INT NOT NULL DEFAULT 0,
    UNIQUE (user_id, name)
);

CREATE INDEX idx_collections_user ON user_memory_collections(user_id);

-- Collection membership: links memories to collections (many-to-many)
CREATE TABLE IF NOT EXISTS collection_memories (
    collection_id UUID NOT NULL REFERENCES user_memory_collections(id) ON DELETE CASCADE,
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    notes TEXT,
    PRIMARY KEY (collection_id, memory_id)
);

CREATE INDEX idx_collection_memories_memory ON collection_memories(memory_id);

-- Global memories view: all memories accessible to a user
CREATE OR REPLACE VIEW user_accessible_memories AS
SELECT
    m.*,
    r.id as source_room_id,
    rm.user_id as accessor_user_id,
    CASE
        WHEN m.scope = 'global' THEN true
        WHEN m.scope = 'user' AND m.owner_user_id = rm.user_id THEN true
        WHEN m.scope = 'room' THEN true
        ELSE false
    END as is_accessible,
    CASE
        WHEN m.room_id = r.id THEN 'local'
        ELSE 'cross_room'
    END as memory_source
FROM memories m
JOIN rooms r ON m.room_id = r.id OR m.scope = 'global'
JOIN room_memberships rm ON r.id = rm.room_id
WHERE m.status = 'active';

-- Add global scope support columns to memories
ALTER TABLE memories ADD COLUMN IF NOT EXISTS promoted_to_global_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS promoted_by_user_id UUID REFERENCES users(id);

COMMENT ON TABLE memory_references IS 'Tracks citations of memories across rooms/sessions';
COMMENT ON TABLE user_memory_collections IS 'User-defined collections of memories that persist across rooms';
COMMENT ON TABLE collection_memories IS 'Many-to-many link between collections and memories';

-- ============================================================
-- LLM IDENTITY DOCUMENTS (stored as memories)
-- ============================================================
-- LLM identity documents use the existing memories table with scope='llm':
--   key='llm_identity:{room_id}', scope='llm' — per-room evolved identity
--   key='user_model:{user_id}', scope='llm' — per-user thinking model
-- The memory versioning system (memory_versions table) tracks identity evolution.
-- Identity is distilled on WebSocket disconnect when 5+ messages occurred in session.

-- ============================================================
-- LLM SELF-MEMORY SUPPORT
-- ============================================================
-- Allow NULL created_by_user_id for LLM-authored memories (scope='llm')
ALTER TABLE memories ALTER COLUMN created_by_user_id DROP NOT NULL;
-- Allow NULL updated_by_user_id for LLM-authored memory versions
ALTER TABLE memory_versions ALTER COLUMN updated_by_user_id DROP NOT NULL;

-- ============================================================
-- KNOWLEDGE GRAPH
-- ============================================================

-- Materialized view: knowledge graph edges from existing relationships
CREATE MATERIALIZED VIEW IF NOT EXISTS knowledge_graph AS
-- Memory references (cross-room citations)
SELECT
    'memory_reference' as edge_type,
    source_memory_id as source_id,
    'memory' as source_type,
    COALESCE(target_message_id::uuid, target_thread_id::uuid, target_room_id) as target_id,
    CASE
        WHEN target_message_id IS NOT NULL THEN 'message'
        WHEN target_thread_id IS NOT NULL THEN 'thread'
        ELSE 'room'
    END as target_type,
    COALESCE(relevance_score, 0.5) as weight,
    referenced_at as created_at
FROM memory_references

UNION ALL

-- Thread forks (genealogy)
SELECT
    'thread_fork' as edge_type,
    parent_thread_id as source_id,
    'thread' as source_type,
    id as target_id,
    'thread' as target_type,
    1.0 as weight,
    created_at
FROM threads WHERE parent_thread_id IS NOT NULL

UNION ALL

-- Message references (reply chains)
SELECT
    'message_reference' as edge_type,
    references_message_id as source_id,
    'message' as source_type,
    id as target_id,
    'message' as target_type,
    1.0 as weight,
    created_at
FROM messages WHERE references_message_id IS NOT NULL

UNION ALL

-- Memory version chains (belief evolution)
SELECT
    'memory_evolution' as edge_type,
    memory_id as source_id,
    'memory' as source_type,
    memory_id as target_id,
    'memory_version' as target_type,
    1.0 as weight,
    updated_at as created_at
FROM memory_versions WHERE version > 1;

CREATE INDEX IF NOT EXISTS idx_knowledge_graph_source ON knowledge_graph(source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_graph_target ON knowledge_graph(target_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_graph_type ON knowledge_graph(edge_type);

-- ============================================================
-- THINKING PROTOCOLS
-- ============================================================

CREATE TABLE IF NOT EXISTS thread_protocols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES rooms(id),
    protocol_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'invoked',
    current_phase INT NOT NULL DEFAULT 0,
    total_phases INT NOT NULL,
    invoked_by_user_id UUID REFERENCES users(id),
    invoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    phase_advanced_at TIMESTAMPTZ,
    concluded_at TIMESTAMPTZ,
    synthesis_memory_id UUID REFERENCES memories(id),
    config JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_thread_protocols_thread ON thread_protocols(thread_id);
CREATE INDEX IF NOT EXISTS idx_thread_protocols_status ON thread_protocols(status)
    WHERE status IN ('invoked', 'active', 'concluding');

CREATE TABLE IF NOT EXISTS protocol_phases (
    protocol_id UUID NOT NULL REFERENCES thread_protocols(id) ON DELETE CASCADE,
    phase_number INT NOT NULL,
    phase_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    PRIMARY KEY (protocol_id, phase_number)
);

-- Link messages to protocol phases for attribution
ALTER TABLE messages ADD COLUMN IF NOT EXISTS protocol_id UUID REFERENCES thread_protocols(id);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS protocol_phase INT;

-- ============================================================
-- TYPING ANALYSIS
-- ============================================================
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS enable_typing_analysis BOOLEAN DEFAULT false;

-- ============================================================
-- TRADING ROOM INTEGRATION
-- ============================================================
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS trading_config JSONB DEFAULT NULL;

-- ============================================================
-- STAKES / COMMITMENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS commitments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(id),
    source_message_id UUID REFERENCES messages(id),  -- message that triggered creation

    -- Content
    claim TEXT NOT NULL,              -- The prediction or commitment
    resolution_criteria TEXT NOT NULL, -- How to determine if it came true
    category TEXT DEFAULT 'prediction', -- 'prediction' | 'commitment' | 'bet'

    -- Lifecycle
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id UUID REFERENCES users(id),  -- NULL for LLM-created
    deadline TIMESTAMPTZ,             -- When it should be resolved
    resolved_at TIMESTAMPTZ,
    resolved_by_user_id UUID REFERENCES users(id),
    resolution TEXT,                  -- 'correct' | 'incorrect' | 'partial' | 'voided'
    resolution_notes TEXT,

    -- Status
    status TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'resolved' | 'voided' | 'expired'
);

CREATE INDEX IF NOT EXISTS idx_commitments_room ON commitments(room_id);
CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(room_id, status);
CREATE INDEX IF NOT EXISTS idx_commitments_deadline ON commitments(deadline) WHERE status = 'active';

-- Confidence levels per participant (including LLM)
CREATE TABLE IF NOT EXISTS commitment_confidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    commitment_id UUID NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),  -- NULL for LLM
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reasoning TEXT                      -- Why this confidence level
);

CREATE INDEX IF NOT EXISTS idx_commitment_confidence ON commitment_confidence(commitment_id);

-- ============================================================
-- MULTI-MODEL ROOMS
-- ============================================================

CREATE TABLE IF NOT EXISTS room_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                  -- e.g., "Aristotle", "Skeptic", "Synthesizer"
    provider TEXT NOT NULL DEFAULT 'anthropic',
    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    identity_prompt TEXT NOT NULL,       -- System prompt for this persona
    personality JSONB DEFAULT '{}',      -- Additional config (temperature, etc.)
    trigger_strategy TEXT DEFAULT 'on_mention',  -- 'on_mention' | 'after_primary' | 'on_disagreement' | 'periodic'
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    display_order INT DEFAULT 0,
    UNIQUE (room_id, name)
);

CREATE INDEX IF NOT EXISTS idx_room_personas_room ON room_personas(room_id);

-- Link messages to personas for attribution
ALTER TABLE messages ADD COLUMN IF NOT EXISTS persona_id UUID REFERENCES room_personas(id);
