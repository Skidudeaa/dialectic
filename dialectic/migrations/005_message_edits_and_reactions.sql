-- Editing, deleting and reacting to messages.
--
-- `messages.is_deleted` has existed since the original schema and every read
-- path already filters on it — but nothing could ever set it, so a typo was
-- permanent. `edited_at` is new: NULL means never edited, which is what lets
-- the client show an "edited" marker only where one is warranted rather than
-- inferring it from timestamps.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;

-- Reactions are their own rows rather than a JSONB blob on the message so that
-- two people reacting at the same time cannot clobber each other with a
-- read-modify-write, and so "who reacted" is answerable without scanning.
--
-- The primary key makes a repeated reaction idempotent: one emoji per person
-- per message, and toggling off is a delete.
CREATE TABLE IF NOT EXISTS message_reactions (
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    emoji TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (message_id, user_id, emoji)
);

-- Reactions are always fetched for a set of messages being rendered.
CREATE INDEX IF NOT EXISTS idx_message_reactions_message
    ON message_reactions(message_id);
