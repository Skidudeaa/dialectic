-- Initial schema for local message cache with FTS5

CREATE TABLE IF NOT EXISTS cached_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  content TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  sender_name TEXT,
  speaker_type TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  cached_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cached_messages_thread
ON cached_messages (thread_id, sequence DESC);

CREATE INDEX IF NOT EXISTS idx_cached_messages_cached
ON cached_messages (cached_at ASC);

-- FTS5 for local full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  content,
  sender_name,
  content=cached_messages,
  content_rowid=rowid,
  tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync with cached_messages
CREATE TRIGGER IF NOT EXISTS cached_messages_ai AFTER INSERT ON cached_messages BEGIN
  INSERT INTO messages_fts(rowid, content, sender_name)
  VALUES (NEW.rowid, NEW.content, NEW.sender_name);
END;

CREATE TRIGGER IF NOT EXISTS cached_messages_ad AFTER DELETE ON cached_messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, sender_name)
  VALUES ('delete', OLD.rowid, OLD.content, OLD.sender_name);
END;

CREATE TRIGGER IF NOT EXISTS cached_messages_au AFTER UPDATE ON cached_messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, sender_name)
  VALUES ('delete', OLD.rowid, OLD.content, OLD.sender_name);
  INSERT INTO messages_fts(rowid, content, sender_name)
  VALUES (NEW.rowid, NEW.content, NEW.sender_name);
END;
