-- 001_initial_schema.sql
-- WHY: All tables for the v2 persistence layer. Covers both migrated
-- v1 data (rooms, messages, pins, journal, predictions, tv_events) and
-- new v2 additions (snapshots, alert_events, manual_overrides,
-- close_observations, fetch_runs, outbox).

-- ── Rooms ──────────────────────────────────────────────────────────────

CREATE TABLE rooms (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    topic          TEXT NOT NULL DEFAULT '',
    linked_book_id TEXT,
    participants   TEXT NOT NULL DEFAULT '[]',  -- JSON array of usernames
    created_at     TEXT NOT NULL
);

-- ── Messages ───────────────────────────────────────────────────────────

CREATE TABLE messages (
    id       TEXT PRIMARY KEY,
    room_id  TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user     TEXT NOT NULL,
    content  TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'user',
    model    TEXT,
    ts       TEXT NOT NULL
);

CREATE INDEX idx_messages_room_ts ON messages(room_id, ts);

-- ── Pins ───────────────────────────────────────────────────────────────

CREATE TABLE pins (
    id        TEXT PRIMARY KEY,
    room_id   TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user      TEXT NOT NULL,
    content   TEXT NOT NULL,
    msg_type  TEXT NOT NULL DEFAULT 'user',
    model     TEXT,
    ts        TEXT NOT NULL
);

CREATE INDEX idx_pins_room ON pins(room_id);

-- ── Journal entries ────────────────────────────────────────────────────

CREATE TABLE journal_entries (
    id             TEXT PRIMARY KEY,
    user           TEXT NOT NULL,
    thesis         TEXT NOT NULL DEFAULT '',
    instrument     TEXT NOT NULL DEFAULT '',
    direction      TEXT NOT NULL DEFAULT '',
    entry_price    REAL,
    exit_price     REAL,
    pnl            REAL,
    tags           TEXT NOT NULL DEFAULT '[]',  -- JSON array
    linked_book_id TEXT,
    notes          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT
);

-- ── Predictions ────────────────────────────────────────────────────────

CREATE TABLE predictions (
    id             TEXT PRIMARY KEY,
    user           TEXT NOT NULL,
    statement      TEXT NOT NULL,
    confidence     REAL NOT NULL,
    deadline       TEXT NOT NULL,
    resolution     TEXT,        -- 'correct' | 'incorrect' | NULL
    resolved_at    TEXT,
    linked_book_id TEXT,
    tags           TEXT NOT NULL DEFAULT '[]',  -- JSON array
    created_at     TEXT NOT NULL
);

-- ── TradingView events ─────────────────────────────────────────────────

CREATE TABLE tv_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    result    TEXT NOT NULL,
    book_id   TEXT,
    binding_id TEXT,
    node_id   TEXT,
    op        TEXT,
    new_value TEXT,   -- JSON-encoded
    detail    TEXT,
    source_ip TEXT
);

CREATE INDEX idx_tv_events_ts ON tv_events(ts DESC);
CREATE INDEX idx_tv_events_book ON tv_events(book_id, ts DESC);

-- ── Thesis snapshots (v2) ──────────────────────────────────────────────

CREATE TABLE thesis_snapshots (
    thesis_id       TEXT NOT NULL,
    revision        INTEGER NOT NULL,
    generated_at    TEXT NOT NULL,
    definition_hash TEXT,
    quality_status  TEXT NOT NULL DEFAULT 'healthy',
    snapshot_json   TEXT NOT NULL,
    PRIMARY KEY (thesis_id, revision)
);

CREATE INDEX idx_snapshots_latest
    ON thesis_snapshots(thesis_id, revision DESC);

-- ── Alert events (v2) ──────────────────────────────────────────────────

CREATE TABLE alert_events (
    event_id       TEXT PRIMARY KEY,
    thesis_id      TEXT NOT NULL,
    revision       INTEGER,
    event_type     TEXT NOT NULL,
    severity       TEXT NOT NULL,
    node_id        TEXT,
    old_value_json TEXT,
    new_value_json TEXT,
    occurred_at    TEXT NOT NULL,
    dedupe_key     TEXT UNIQUE
);

CREATE INDEX idx_alerts_thesis_time
    ON alert_events(thesis_id, occurred_at DESC);
CREATE INDEX idx_alerts_type_time
    ON alert_events(event_type, occurred_at DESC);

-- ── Manual overrides (v2) ──────────────────────────────────────────────

CREATE TABLE manual_overrides (
    override_id TEXT PRIMARY KEY,
    thesis_id   TEXT NOT NULL,
    target_type TEXT NOT NULL,  -- 'node' | 'marketField' | 'instrument'
    target_id   TEXT NOT NULL,
    field       TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    actor       TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    cleared_at  TEXT,
    status      TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'expired' | 'cleared'
);

CREATE INDEX idx_overrides_thesis_status
    ON manual_overrides(thesis_id, status);

-- ── Close observations (v2) ────────────────────────────────────────────

CREATE TABLE close_observations (
    thesis_id     TEXT NOT NULL,
    node_id       TEXT NOT NULL,
    market_date   TEXT NOT NULL,
    threshold_key TEXT NOT NULL,
    close_value   REAL NOT NULL,
    qualifies     INTEGER NOT NULL DEFAULT 1,  -- 1 = above threshold, 0 = below
    captured_at   TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'derived',  -- 'derived' | 'tv_webhook'
    PRIMARY KEY (thesis_id, node_id, market_date, threshold_key)
);

-- ── Fetch runs (v2) ────────────────────────────────────────────────────

CREATE TABLE fetch_runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id           TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL DEFAULT 'running',  -- 'running' | 'success' | 'failed'
    provider_values_json TEXT,  -- raw fetched prices/probabilities for restart recovery
    diagnostics_json    TEXT,
    revision            INTEGER
);

CREATE INDEX idx_fetch_runs_thesis
    ON fetch_runs(thesis_id, run_id DESC);

-- ── Outbox (v2) ────────────────────────────────────────────────────────

CREATE TABLE outbox (
    outbox_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL DEFAULT 'dialectic',
    thesis_id    TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'sent' | 'failed'
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_outbox_pending
    ON outbox(status, created_at) WHERE status = 'pending';
