-- 019_the_duel.sql — the Sunday Round becomes a three-handed duel.
--
-- Two additive, nullable-or-defaulted columns on the append-only forecast
-- history. No backfill, no rewrite, no reader breaks: every existing row
-- becomes a human forecast with no peer guess, which is exactly what it is.
--
-- WHY `peer_forecast` lives on the SAME row as `confidence` rather than in a
-- table of its own: they are entered together in one tap and revised
-- together, so a second table would be a join that can only ever be 1:1 with
-- the row beside it. The append-only history then carries both, which means
-- the empathy error is time-weighted for free, by the same day-loop.
--
-- WHY `actor` rather than leaning on `user_id IS NULL`: NULL already means
-- "we do not know who", and `CommitmentManager.record_confidence` defaults
-- user_id to None, so a caller that forgets to pass one writes a row
-- indistinguishable from the house's. An explicit actor cannot collide, and
-- it is what lets `_round_state` keep the two-human blindness rule intact
-- while a third forecaster sits in the same table.

ALTER TABLE commitment_confidence
    ADD COLUMN IF NOT EXISTS peer_forecast double precision,
    ADD COLUMN IF NOT EXISTS actor text NOT NULL DEFAULT 'human';

-- Same bounds as `confidence`. A probability outside [0,1] is not a
-- probability, and the scorer would silently produce a Brier above 1.
ALTER TABLE commitment_confidence
    DROP CONSTRAINT IF EXISTS commitment_confidence_peer_forecast_check;
ALTER TABLE commitment_confidence
    ADD CONSTRAINT commitment_confidence_peer_forecast_check
    CHECK (peer_forecast IS NULL
           OR (peer_forecast >= 0::double precision
               AND peer_forecast <= 1::double precision));

ALTER TABLE commitment_confidence
    DROP CONSTRAINT IF EXISTS commitment_confidence_actor_check;
ALTER TABLE commitment_confidence
    ADD CONSTRAINT commitment_confidence_actor_check
    CHECK (actor IN ('human', 'house'));

-- The house forecasts once per question and revises; the read path fetches
-- its history by commitment. Partial because human rows outnumber house rows
-- and only the house needs finding by actor.
CREATE INDEX IF NOT EXISTS idx_commitment_confidence_house
    ON commitment_confidence (commitment_id, recorded_at)
    WHERE actor = 'house';
