-- schema.sql — PostgreSQL DDL

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
-- Trigram matching for the entity/restatement recall lane (006)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
    primary_model TEXT NOT NULL DEFAULT 'claude-sonnet-5',
    provoker_model TEXT NOT NULL DEFAULT 'claude-sonnet-5',
    auto_interjection_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    interjection_turn_threshold INT NOT NULL DEFAULT 4,
    semantic_novelty_threshold FLOAT NOT NULL DEFAULT 0.7,
    last_trading_push_at TIMESTAMPTZ,
    trading_push_count INTEGER NOT NULL DEFAULT 0
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
    edited_at TIMESTAMPTZ,
    metadata JSONB,
    UNIQUE (thread_id, sequence)
);

CREATE INDEX idx_messages_thread ON messages(thread_id, sequence);
CREATE INDEX idx_messages_metadata_source ON messages ((metadata->>'source'));

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
    embedding VECTOR(1024),
    -- Whose statement this memory captures (006) — distinct from created_by_user_id (who saved it)
    speaker_user_id UUID REFERENCES users(id),
    -- Supersession: valid_from = created_at, valid_until = superseded_at (006)
    superseded_at TIMESTAMPTZ,
    superseded_by_memory_id UUID REFERENCES memories(id),
    -- Full-text lane (006)
    fts TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', coalesce(key, '') || ' ' || coalesce(content, ''))) STORED
);

CREATE INDEX idx_memories_room ON memories(room_id);
CREATE INDEX idx_memories_status ON memories(room_id, status);
CREATE INDEX idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_memories_fts ON memories USING gin (fts);

-- Web Push (VAPID) subscriptions for the installed PWA (007)
CREATE TABLE web_push_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_success_at TIMESTAMPTZ
);

CREATE INDEX idx_web_push_user ON web_push_subscriptions(user_id);
CREATE INDEX idx_memories_content_trgm ON memories USING gin (content gin_trgm_ops);
CREATE INDEX idx_memories_key_trgm ON memories USING gin (key gin_trgm_ops);
CREATE INDEX idx_memories_speaker ON memories(room_id, speaker_user_id);

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
    revoked_at TIMESTAMPTZ,
    -- Why the session ended: 'logout' | 'evicted_by_new_login' |
    -- 'password_reset'. Lets an evicted device tell the user what happened
    -- instead of dropping to a blank auth screen. NULL = active, or revoked
    -- before this column existed.
    revoked_reason TEXT
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

-- Reactions
-- Rows rather than a JSONB blob on the message: concurrent reactions cannot
-- clobber each other, and the primary key makes one emoji per person per
-- message idempotent (toggling off is a delete).
CREATE TABLE message_reactions (
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    emoji TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (message_id, user_id, emoji)
);

CREATE INDEX idx_message_reactions_message ON message_reactions(message_id);

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

-- Personal promotion grants: opt one user into cross-room recall without
-- changing the shared source memory or another member's LLM context.
CREATE TABLE IF NOT EXISTS user_memory_promotions (
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (memory_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_memory_promotions_user
    ON user_memory_promotions(user_id, memory_id);

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
COMMENT ON TABLE user_memory_promotions IS 'Per-user grants for automatic cross-room recall of shared memories';
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
    model TEXT NOT NULL DEFAULT 'claude-sonnet-5',
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

-- ============================================================
-- SCHEDULER (migration 008 — fusion amendment; Q3 plan P3 organ)
-- ============================================================

-- Generalized idempotency ledger: one row per (job, interval bucket); only
-- the INSERT winner runs the job, so restarts can never double-fire.
CREATE TABLE IF NOT EXISTS scheduled_job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',   -- running | success | error
    detail JSONB,
    UNIQUE (job_name, scheduled_for)
);

CREATE INDEX IF NOT EXISTS idx_sjr_job_time
    ON scheduled_job_runs (job_name, scheduled_for DESC);

-- Which tradingDesk thesis book a room is bound to (NULL = not a trading room).
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS linked_book_id TEXT;

-- ============================================================
-- ATTACHMENTS (migration 009 — media: images / video / files)
-- ============================================================

-- WHY message_id is NULLABLE: the upload happens BEFORE the message that
-- carries it exists — the client POSTs bytes, gets an attachment id back,
-- then sends the message, then binds. Orphan policy: rows still unbound 24h
-- after created_at are future-sweep candidates.
CREATE TABLE IF NOT EXISTS attachments (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    message_id UUID REFERENCES messages(id),   -- NULL until the send_message that references it lands
    uploader_user_id UUID NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,                        -- image | video | file
    mime TEXT NOT NULL,
    bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    width INT, height INT,
    original_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,                -- relative to MEDIA_ROOT
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_attachments_room ON attachments(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha ON attachments(room_id, sha256);

-- ============================================================
-- LLM SELF-MODEL (migration 001; tool_calls column from migration 010)
-- ============================================================
-- These two tables were previously only in migrations/001_llm_self_model.sql
-- and missing from this file — a fresh database built from schema.sql alone
-- could not log a single orchestrator decision. Folded in verbatim, plus the
-- tool_calls JSONB column from migration 010.

-- Layer 1: Decision Log (append-only observable truth)
-- ARCHITECTURE: Every orchestrator run — speak or silent — produces
-- a decision record. This is the self-model's raw event log.
CREATE TABLE IF NOT EXISTS llm_decisions (
    id BIGSERIAL PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    thread_id UUID NOT NULL REFERENCES threads(id),
    triggered_by_message_id UUID REFERENCES messages(id),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- The decision itself
    should_interject BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    use_provoker BOOLEAN NOT NULL DEFAULT FALSE,
    considered_reasons TEXT[] NOT NULL DEFAULT '{}',

    -- Context at decision time
    human_turn_count INTEGER,
    semantic_novelty REAL,
    unsurfaced_memory_count INTEGER,
    speaker_balance JSONB,               -- {"user_id": msg_count, ...}
    message_count_in_thread INTEGER,

    -- Outcome (NULL if silence)
    response_message_id UUID REFERENCES messages(id),
    mode TEXT NOT NULL,                   -- primary | provoker | protocol | mention | annotator | silence
    tool_calls JSONB,                     -- label-stamped trace when the tool loop ran (migration 010)

    -- Effectiveness (populated async after response)
    effectiveness_score REAL,             -- NULL until measured
    human_responded BOOLEAN,
    human_response_length INTEGER,
    human_response_delay_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_llm_decisions_room
    ON llm_decisions(room_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_decisions_thread
    ON llm_decisions(thread_id, decided_at DESC);

-- Layer 2: Participation State (per-room reduced state)
-- ARCHITECTURE: Derived from the decision log. Updated after each
-- decision. The LLM's self-model for "what have I been doing?"
CREATE TABLE IF NOT EXISTS llm_participation_state (
    room_id UUID PRIMARY KEY REFERENCES rooms(id),

    -- Temporal awareness
    last_spoke_at TIMESTAMPTZ,
    last_spoke_message_id UUID REFERENCES messages(id),
    turns_since_last_spoke INTEGER DEFAULT 0,
    seconds_since_last_spoke INTEGER,
    total_messages_sent INTEGER DEFAULT 0,
    total_silences INTEGER DEFAULT 0,

    -- Mode tracking
    primary_count INTEGER DEFAULT 0,
    provoker_count INTEGER DEFAULT 0,
    protocol_count INTEGER DEFAULT 0,
    last_mode TEXT,

    -- Confidence trajectory
    avg_confidence_last_10 REAL,
    confidence_trend TEXT DEFAULT 'stable',  -- rising | falling | stable
    recent_confidences REAL[] DEFAULT '{}',  -- last 10 confidence values

    -- Contribution balance
    llm_message_ratio REAL,               -- LLM messages / total messages in room
    avg_response_length INTEGER,

    -- Effectiveness signals
    avg_human_response_length_after INTEGER,
    engaged_count INTEGER DEFAULT 0,       -- humans responded substantively
    ignored_count INTEGER DEFAULT 0,       -- LLM spoke, no human response within 3 msgs
    effectiveness_avg REAL,

    -- Conversation shape
    active_thread_count INTEGER DEFAULT 1,
    total_fork_count INTEGER DEFAULT 0,
    last_memory_operation_at TIMESTAMPTZ,

    -- Session awareness
    current_session_start TIMESTAMPTZ,
    session_count INTEGER DEFAULT 0,
    days_since_last_session REAL,

    -- Participation FSM (migration 011, llm/participation_fsm.py)
    fsm_state TEXT,                        -- engaged | awaiting_human | question_pending | ignored | dormant
    state_entered_at TIMESTAMPTZ,          -- the sweep's follow-up clock keys off this
    state_source TEXT,                     -- observed | reconciled | inferred

    -- Meta
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- HOME BASE (migration 013)
-- ============================================================
-- One real Home room: is_home marks it and the partial unique index
-- enforces the singleton in PostgreSQL. The baseline stays data-free —
-- every environment (including a fresh database) runs idempotent
-- migrations/013_home_base.sql to create Home, its 'Main' thread, and
-- their bootstrap events. Memberships come only from the separately
-- reviewed deploy/activate_home_founders.sql transaction.
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_home BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_single_home
    ON rooms (is_home)
    WHERE is_home;

ALTER TABLE room_memberships ADD COLUMN IF NOT EXISTS can_manage_home BOOLEAN NOT NULL DEFAULT FALSE;

-- ============================================================
-- FIELD MARKS (migration 017)
-- ============================================================
-- One table, two row species in mark_kind — 'relation' (an asserted
-- reasoning relationship, inferred or explicit) and 'review' (a human action
-- on a prior mark). Append-only: no code path UPDATEs or DELETEs a row;
-- review state is derived at read time (field_marks.py). The partial unique
-- index on (room_id, dedup_key) is the structural guarantee that a
-- human-corrected mark is never re-asserted by the inference job. Appended
-- to the baseline in the same commit as the migration — 014's reading_items
-- was not, and that gap is a recorded trap (dialectic/CLAUDE.md amendment).
CREATE TABLE IF NOT EXISTS field_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(id) ON DELETE SET NULL,  -- NULL = room-wide
    mark_kind TEXT NOT NULL CHECK (mark_kind IN ('relation','review')),
    relation TEXT,   -- §14.3 vocabulary; comment-documented, contract-pinned, no CHECK (the list may grow)
    action TEXT CHECK (action IN ('confirm','contest','correct','supersede','split','merge')),
    origin TEXT CHECK (origin IN ('explicit','inferred')),
    deliberative_status TEXT NOT NULL DEFAULT 'active'
        CHECK (deliberative_status IN ('active','accepted','rejected','resolved','withdrawn')),
    subjects JSONB NOT NULL DEFAULT '[]',  -- array of {entity,id,field} — exactly WorkspaceSourceRef
    target_mark_id UUID REFERENCES field_marks(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}',   -- quote/span, note, merge_group, action extras
    supersedes_id UUID REFERENCES field_marks(id),  -- replacement → what it replaces
    caused_by_id  UUID REFERENCES field_marks(id),  -- replacement → the review row that caused it
    actor_user_id UUID REFERENCES users(id),        -- NULL = Dialectic
    provenance TEXT NOT NULL,                       -- 'field_inference' | 'human'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dedup_key TEXT,                                 -- inference idempotency; set on ALL relation rows, NULL on reviews
    CONSTRAINT relation_iff_relation CHECK ((mark_kind='relation') = (relation IS NOT NULL)),
    CONSTRAINT action_iff_review     CHECK ((mark_kind='review')   = (action   IS NOT NULL)),
    CONSTRAINT review_has_target     CHECK (mark_kind <> 'review' OR target_mark_id IS NOT NULL),
    CONSTRAINT review_has_actor      CHECK (mark_kind <> 'review' OR actor_user_id  IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_field_marks_dedup
    ON field_marks (room_id, dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_field_marks_room     ON field_marks (room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_field_marks_target   ON field_marks (target_mark_id);
CREATE INDEX IF NOT EXISTS idx_field_marks_subjects ON field_marks USING GIN (subjects jsonb_path_ops);

COMMENT ON TABLE field_marks IS
    'The Field: room-local, append-only reasoning marks (inferred + human review). See field_marks.py.';
