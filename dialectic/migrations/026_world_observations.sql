-- 026_world_observations.sql — the consumer's durable row.
--
-- ARCHITECTURE (docs/WORLD_LENS_VISION.md, the World Lens plan's Step 1):
-- `world_signals.py`'s store is ephemeral and process-local — restart the
-- process and every contact is gone. This table is the first durable trace
-- of what a live feed reported, and it is evidence ABOUT a scope, never
-- geometry of its own: `scope_id` is a hard FK into `geo_scopes`, and
-- nothing here can be read as a place a human did not already confirm or a
-- source already reported. Same standing as a `reading_item` — a citation,
-- not authority.
--
-- WHY upsert on (scope_id, signal_id) rather than append-only rows: a
-- contact loitering in the Strait polls every five minutes; recording it as
-- one growing row (`seen_count`, `last_seen_at`) is the difference between a
-- fact ("this has been here two hours") and a flood (700 identical rows).
-- `first_seen_at` is what lets `world_watch.py` tell a genuinely NEW contact
-- (worth possibly interjecting about) from one it already knew about.
--
-- WHY `provider` is constrained to the terms-cleared set: `usgs` (PD) and
-- `launch` (CC-BY) persist freely, `adsb` (ODbL) persists with the credit
-- carried in `provenance`. `iss` is ephemeral-only (no redistribution terms
-- recorded) and `firms`/`ais`/`opensky` never persist at all — see
-- `llm/world_watch.py::PERSISTABLE_PROVIDERS`, the single source of truth
-- this CHECK mirrors so a future adapter cannot silently start persisting.
--
-- Retention: `llm/world_watch.py::run` DELETEs rows past a 30-day ceiling on
-- every tick (see its `ponytail:` comment) — a replay store is a later
-- decision, not this one.
CREATE TABLE IF NOT EXISTS world_observations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id       UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    scope_id      UUID NOT NULL REFERENCES geo_scopes(id),   -- the HUMAN scope it fell inside
    provider      TEXT NOT NULL CHECK (provider IN ('usgs', 'adsb', 'launch')),
    signal_id     TEXT NOT NULL,                              -- world_signal:<provider>:<source_id>
    layer         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    geometry      JSONB NOT NULL,                             -- the point as reported; provenance says whose
    provenance    JSONB NOT NULL,                             -- provider, source id/URL, credit, licence
    details       JSONB NOT NULL DEFAULT '{}',
    observed_at   TIMESTAMPTZ,
    retrieved_at  TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seen_count    INT NOT NULL DEFAULT 1,
    UNIQUE (scope_id, signal_id)                               -- one row per contact per scope; upsert bumps last_seen/count
);
CREATE INDEX IF NOT EXISTS idx_world_observations_room ON world_observations (room_id, last_seen_at DESC);
COMMENT ON TABLE world_observations IS
    'World Lens consumer: provider contacts observed inside a human-confirmed scope. Evidence, never authority. See llm/world_watch.py.';
