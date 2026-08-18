-- The claims ledger: predictions grow provenance + a reference forecast,
-- and confidence becomes an append-only history instead of a single column.
--
-- ORDER IS LOAD-BEARING. The confidence repair must run BEFORE the history
-- seed below, or the seed copies percent-scale poison (a live 75.0 row
-- exists) into prediction_confidence as gospel. Statement order in this
-- file is the only thing enforcing that.

-- 1. Repair percent-scale confidences (e.g. 75.0 → 0.75). Legitimate
--    values are 0.0–1.0, so anything above 1.0 is a percent-scale write
--    from before the door range-validated.
UPDATE predictions SET confidence = confidence / 100.0 WHERE confidence > 1.0;

-- 2. Provenance + reference-forecast + resolution columns.
--    source_type: 'human' | 'llm' | 'dialectic_commitment' | 'newsletter' | 'polymarket'
--    base_rate: the captured reference forecast (Polymarket price when
--    linkable) that Brier skill scores are computed against.
--    resolution_spec: JSON for deterministic auto-resolution (Phase 2).
ALTER TABLE predictions ADD COLUMN source_type TEXT NOT NULL DEFAULT 'human';
ALTER TABLE predictions ADD COLUMN source_label TEXT;
ALTER TABLE predictions ADD COLUMN source_ref TEXT;
ALTER TABLE predictions ADD COLUMN base_rate REAL;
ALTER TABLE predictions ADD COLUMN base_rate_source TEXT;
ALTER TABLE predictions ADD COLUMN resolution_notes TEXT;
ALTER TABLE predictions ADD COLUMN resolution_spec TEXT;  -- JSON

-- 3. Existing rows were all human-entered by their `user`.
UPDATE predictions SET source_label = user WHERE source_label IS NULL;

-- 4. Append-only confidence history. Calibration scores read the LAST row
--    at/before resolved_at, so belief updates never overwrite the record
--    of what was believed when.
CREATE TABLE prediction_confidence (
    id            TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
    actor         TEXT NOT NULL,
    confidence    REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasoning     TEXT,
    recorded_at   TEXT NOT NULL
);
CREATE INDEX idx_prediction_confidence_lookup
    ON prediction_confidence(prediction_id, recorded_at);

-- 5. Seed one history row per existing prediction from its (now repaired)
--    confidence, stamped at creation time so the last-before-resolution
--    rule finds it for already-resolved rows.
INSERT INTO prediction_confidence (id, prediction_id, actor, confidence, reasoning, recorded_at)
SELECT lower(hex(randomblob(16))), id, user, confidence, NULL, created_at
FROM predictions;
