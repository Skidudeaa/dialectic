-- ════════════════════════════════════════════════════════════════════════
-- 003 — structured message kinds
--
-- Messages gain a `kind` discriminator and a `meta` JSON blob so the room can
-- carry shared article clippings and code exhibits as first-class entries
-- (not just plain text). Existing rows default to kind='text' / meta=NULL.
--
--   kind = 'text'    → plain dispatch (meta NULL)
--   kind = 'article' → meta = {"source","title","take"}
--   kind = 'code'    → meta = {"fn","lang","code"}
-- ════════════════════════════════════════════════════════════════════════

ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'text';
ALTER TABLE messages ADD COLUMN meta TEXT;
