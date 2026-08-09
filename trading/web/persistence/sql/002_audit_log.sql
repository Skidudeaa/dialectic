-- 002_audit_log.sql
-- WHY: Destructive actions (trade kill, scenario apply, builder delete)
-- need a durable audit trail. Unit 10 used an in-memory token map; this
-- migration replaces it with a SQLite-backed token store and adds the
-- audit_log table that destructive routes write into.
--
-- Re-running this migration is a no-op — every CREATE uses IF NOT EXISTS.

-- ── Audit log ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,           -- ISO8601 UTC
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,           -- e.g. "trade.kill"
    target        TEXT NOT NULL,           -- e.g. "TRD-XOP-HORMUZ"
    reason        TEXT,
    confirm_token TEXT,                    -- token used (NULL if no confirm flow)
    payload_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

-- ── Confirm tokens ─────────────────────────────────────────────────────
-- WHY: Persisted (rather than in-memory) so a process restart between
-- "issue token" and "consume token" doesn't lose the second-step grant.
-- Token + (actor, action, target) is checked atomically on consume so a
-- token issued for "trade.kill TRD-A" cannot be replayed against TRD-B.

CREATE TABLE IF NOT EXISTS confirm_tokens (
    token       TEXT PRIMARY KEY,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL,
    issued_at   TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    consumed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_confirm_tokens_expires ON confirm_tokens(expires_at);
