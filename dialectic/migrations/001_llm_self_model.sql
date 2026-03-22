-- Migration 001: LLM Persistent Self-Model
--
-- WHY: The LLM participant needs accumulated awareness of its own
-- participation patterns. Currently, every interjection decision is
-- ephemeral — the OrchestrationResult is discarded after each message.
-- These tables give the LLM a queryable history of its own behavior.

-- ============================================================
-- Layer 1: Decision Log (append-only observable truth)
-- ============================================================
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

-- ============================================================
-- Layer 2: Participation State (per-room reduced state)
-- ============================================================
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

    -- Meta
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
