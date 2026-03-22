-- cc-sidecar SQLite schema
-- WHY: Event-sourced observability store for Claude Code sessions.
-- ARCHITECTURE: Append-only raw_events as source of truth; derived tables
-- (sessions, agents, tool_calls, tasks, files, alerts) are fully
-- reconstructable by replaying events through the reducer.

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA auto_vacuum = INCREMENTAL;
PRAGMA foreign_keys = OFF;  -- OFF for out-of-order spool replay tolerance

-- ============================================================
-- Raw event log: append-only source of truth
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at_ms INTEGER NOT NULL,
    mono_seq      INTEGER NOT NULL,
    session_id    TEXT    NOT NULL,
    agent_id      TEXT,                    -- NULL for main agent
    source_kind   TEXT    NOT NULL,        -- hook | statusline | git | transcript
    event_name    TEXT    NOT NULL,
    payload_json  TEXT    NOT NULL,        -- REDACTED before storage
    payload_size  INTEGER NOT NULL,        -- original pre-truncation size in bytes
    dedup_hash    TEXT    NOT NULL UNIQUE, -- SHA-256 of upstream payload only (excl. envelope)
    emitter_version TEXT  NOT NULL
);

-- WHY: The most common query is "recent events for this session" — without
-- this composite index it degrades from 0.8ms to 187ms at 100K rows.
CREATE INDEX IF NOT EXISTS idx_re_session_time
    ON raw_events(session_id, received_at_ms);
CREATE INDEX IF NOT EXISTS idx_re_session_event
    ON raw_events(session_id, event_name);

-- ============================================================
-- Session metadata (updated from SessionStart + statusline)
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
    session_id          TEXT PRIMARY KEY,
    source              TEXT,              -- startup | resume | clear (original creation only)
    model               TEXT,
    cwd                 TEXT,
    project_dir         TEXT,
    started_at_ms       INTEGER,
    last_seen_at_ms     INTEGER,
    ended_at_ms         INTEGER,
    end_reason          TEXT,
    context_used_pct    REAL,
    context_remaining_pct REAL,
    total_cost_usd      REAL    DEFAULT 0.0,
    total_duration_ms   INTEGER,
    total_lines_added   INTEGER,
    total_lines_removed INTEGER,
    compaction_count    INTEGER DEFAULT 0,
    last_compacted_at_ms INTEGER,
    worktree_path       TEXT,
    worktree_branch     TEXT
);

-- ============================================================
-- Agent state (derived by reducer)
-- ============================================================
CREATE TABLE IF NOT EXISTS agents (
    agent_pk        TEXT PRIMARY KEY,      -- main:<session_id> or sub:<session_id>:<agent_id>
    session_id      TEXT NOT NULL,
    agent_id        TEXT,
    parent_agent_pk TEXT,                  -- for nested subagents (nullable)
    agent_type      TEXT NOT NULL,
    state           TEXT NOT NULL,         -- idle | running_tool | awaiting_perm | blocked | retrying | finished | orphaned
    state_source    TEXT NOT NULL,         -- observed | inferred
    is_compacting   INTEGER DEFAULT 0,    -- flag (preserves underlying state through compaction)
    started_at_ms   INTEGER,
    last_event_at_ms INTEGER,
    stopped_at_ms   INTEGER,
    last_tool_name  TEXT,
    last_resource   TEXT,
    last_summary    TEXT,
    visibility_mode TEXT NOT NULL          -- full | lifecycle_only
);

CREATE INDEX IF NOT EXISTS idx_agents_session
    ON agents(session_id);

-- ============================================================
-- Tool calls (derived by reducer)
-- ============================================================
CREATE TABLE IF NOT EXISTS tool_calls (
    tool_use_id   TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    agent_pk      TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    status        TEXT NOT NULL,           -- started | success | failure | denied
    started_at_ms INTEGER NOT NULL,
    ended_at_ms   INTEGER,
    input_summary TEXT,                    -- REDACTED one-liner (not raw JSON)
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_tc_agent
    ON tool_calls(agent_pk, started_at_ms);
CREATE INDEX IF NOT EXISTS idx_tc_session
    ON tool_calls(session_id, started_at_ms);

-- ============================================================
-- Task/plan tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    subject         TEXT NOT NULL,
    description     TEXT,
    owner_agent_pk  TEXT,
    status          TEXT NOT NULL,         -- planned | running | blocked | completed | unknown
    status_source   TEXT NOT NULL,         -- observed | custom_plan | inferred
    created_at_ms   INTEGER,
    completed_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tasks_session
    ON tasks(session_id);

-- ============================================================
-- File ownership and diff tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS files (
    session_id          TEXT NOT NULL,
    path                TEXT NOT NULL,
    last_writer_agent_pk TEXT,
    ownership_source    TEXT NOT NULL,     -- observed | inferred | unknown
    added_lines         INTEGER,
    removed_lines       INTEGER,
    git_status          TEXT,
    last_changed_at_ms  INTEGER,
    reconciled_at_ms    INTEGER,          -- when last git reconciliation ran
    PRIMARY KEY (session_id, path)
);

CREATE INDEX IF NOT EXISTS idx_files_session
    ON files(session_id);

-- ============================================================
-- Alerts
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    severity    TEXT    NOT NULL,          -- info | warn | error
    kind        TEXT    NOT NULL,          -- permission_denied | stuck | orphaned | compaction | config_change | skill_change
    message     TEXT    NOT NULL,
    created_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_alerts_active
    ON alerts(session_id, resolved_at_ms);

-- ============================================================
-- Dead letter queue for unparseable events
-- ============================================================
CREATE TABLE IF NOT EXISTS dead_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at_ms INTEGER NOT NULL,
    raw_payload   TEXT    NOT NULL,
    parse_error   TEXT    NOT NULL
);

-- ============================================================
-- Schema version tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');
