-- 027_world_observations_firms.sql — NASA FIRMS joins the persistable set.
--
-- WHY: migration 026 constrained `provider` to the three terms-cleared feeds
-- and left `firms` out only because it was dark (no MAP_KEY). NASA's data
-- policy is open and unrestricted; FIRMS asks for acknowledgement, which the
-- adapter's `credit` carries into `provenance`:
--   "We acknowledge the use of data and/or imagery from NASA's Fire
--    Information for Resource Management System (FIRMS)
--    (https://earthdata.nasa.gov/firms), part of NASA's EOSDIS."
-- Mirrors `llm/world_watch.py::PERSISTABLE_PROVIDERS` exactly, as 026 did.
--
-- A fires row is a CELL-DAY (world_adapters._merge_fire_cells) and carries
-- `details.baseline_days` / `details.novel` written by world_watch's scoring
-- against the room's own 30-day history — a recurring cell is a flare, a
-- novel one is the news. `iss`, AIS and OpenSky remain excluded.
ALTER TABLE world_observations DROP CONSTRAINT IF EXISTS world_observations_provider_check;
ALTER TABLE world_observations
    ADD CONSTRAINT world_observations_provider_check
    CHECK (provider IN ('usgs', 'adsb', 'launch', 'firms'));
