-- 009_attachments.sql
-- Media attachments (images / video / files) for room messages.
--
-- WHY message_id is NULLABLE: the upload happens BEFORE the message that
-- carries it exists — the client POSTs bytes, gets an attachment id back,
-- then sends the message, then binds. A NOT NULL here would force the
-- bytes to travel inside the send_message payload, which is exactly the
-- design this table exists to avoid.
--
-- ORPHAN POLICY (not implemented this pass): rows whose message_id is still
-- NULL 24h after created_at are sweep candidates — the user picked a file
-- and never sent the message. A future sweeper deletes the row AND the file
-- at storage_path, but only when no OTHER row shares that sha256 in the
-- room (dedup means one blob can back several rows).

CREATE TABLE IF NOT EXISTS attachments (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    message_id UUID REFERENCES messages(id),   -- NULL until the send_message that references it lands
    uploader_user_id UUID NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,                        -- image | video | file
    mime TEXT NOT NULL,
    bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    width INT, height INT,
    original_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_attachments_room ON attachments(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha ON attachments(room_id, sha256);
