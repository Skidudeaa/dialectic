-- 023: drop three tables no code path writes (audit 2026-08-29).
-- user_pins: zero references anywhere. user_memory_collections /
-- collection_memories: write methods had no caller; the only reader
-- (auto-inject lane) therefore always returned []. All three are empty in
-- production. user_memory_promotions is NOT touched -- it is live.
DROP TABLE IF EXISTS collection_memories;
DROP TABLE IF EXISTS user_memory_collections;
DROP TABLE IF EXISTS user_pins;
