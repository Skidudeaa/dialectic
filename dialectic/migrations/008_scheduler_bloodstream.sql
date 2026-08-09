-- 008_scheduler_bloodstream.sql
-- The scheduler organ (pulled forward from Q3 plan Phase 3 by the fusion
-- amendment) + the room->thesis-book binding the bloodstream jobs key on.
--
-- scheduled_job_runs is the GENERALIZED idempotency ledger: one row per
-- (job, interval bucket). Restart-heavy operation can never double-fire a
-- job because only the INSERT winner runs it. Phase 3's planned
-- night_shift_runs ledger is superseded by this table — night-shift and
-- brief jobs register on the same scheduler and write the same ledger.

CREATE TABLE IF NOT EXISTS scheduled_job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    -- running | success | error
    status TEXT NOT NULL DEFAULT 'running',
    detail JSONB,
    UNIQUE (job_name, scheduled_for)
);

CREATE INDEX IF NOT EXISTS idx_sjr_job_time
    ON scheduled_job_runs (job_name, scheduled_for DESC);

-- Which tradingDesk thesis book a room is bound to (NULL = not a trading
-- room). The bloodstream jobs (reconcile pull, freshness watchdog) iterate
-- rooms WHERE linked_book_id IS NOT NULL.
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS linked_book_id TEXT;

UPDATE rooms SET linked_book_id = 'iran-hormuz-graph'
    WHERE id = '56ba2f1e-5c70-4290-a77d-52404f0095da';
UPDATE rooms SET linked_book_id = 'trump-tariffs-graph'
    WHERE id = '8adcabb7-817a-4802-87c6-3bfd42e6a9eb';
