-- The paper book: an append-only fill ledger + a nightly equity mark.
--
-- ARCHITECTURE: positions and cash are DERIVED by SUM over paper_fills at
-- read time — there are no positions/cash tables to drift out of sync with
-- the ledger. Deposits are fills too (kind='deposit', symbol='CASH',
-- price=1.0, quantity=dollars), so one table is the whole book. Shadow
-- worlds (Phase 8) are just more book_id strings ('shadow:consensus:<book>')
-- — this schema needs nothing new for them.

CREATE TABLE paper_fills (
    id            TEXT PRIMARY KEY,
    book_id       TEXT NOT NULL,
    user          TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'trade',   -- 'trade' | 'deposit'
    symbol        TEXT NOT NULL,                   -- 'CASH' for deposits
    side          TEXT NOT NULL,                   -- 'buy' | 'sell'
    quantity      REAL NOT NULL,
    price         REAL NOT NULL,
    rationale     TEXT NOT NULL DEFAULT '',
    node_id       TEXT,
    prediction_id TEXT,
    source_key    TEXT,
    created_at    TEXT NOT NULL
);

-- Idempotent writes via the optional source key (006's pattern): a retried
-- accept lands exactly one fill. Keys stay internal persistence coordinates
-- and are never returned by the public API.
CREATE UNIQUE INDEX idx_paper_fills_source_key
    ON paper_fills(source_key) WHERE source_key IS NOT NULL;
CREATE INDEX idx_paper_fills_book_created
    ON paper_fills(book_id, created_at);

-- One equity mark per book per day, written by the 04:30 UTC maintenance
-- step (after the US close). positions_json snapshots {symbol: {qty, close}}
-- so a later day whose Yahoo fetch fails can reuse the last known close.
CREATE TABLE equity_marks (
    book_id        TEXT NOT NULL,
    mark_date      TEXT NOT NULL,
    equity         REAL NOT NULL,
    cash           REAL NOT NULL,
    spy_close      REAL NOT NULL,
    positions_json TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    PRIMARY KEY (book_id, mark_date)
);
