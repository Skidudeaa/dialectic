-- Performance indexes for Dialectic
-- Run with: psql dialectic < migrations/add_indexes.sql

-- Messages table: thread lookup and sequence ordering
CREATE INDEX IF NOT EXISTS idx_messages_thread_sequence
    ON messages(thread_id, sequence);

-- Messages table: full-text search
CREATE INDEX IF NOT EXISTS idx_messages_search
    ON messages USING gin(search_vector);

-- Events table: room event streaming
CREATE INDEX IF NOT EXISTS idx_events_room_sequence
    ON events(room_id, sequence);

-- Room memberships: user's room list
CREATE INDEX IF NOT EXISTS idx_room_memberships_user
    ON room_memberships(user_id);

-- User presence: room presence queries
CREATE INDEX IF NOT EXISTS idx_user_presence_room
    ON user_presence(room_id, user_id);

-- Message receipts: unread count queries
CREATE INDEX IF NOT EXISTS idx_message_receipts_user
    ON message_receipts(user_id, receipt_type);

-- Threads table: room thread listing
CREATE INDEX IF NOT EXISTS idx_threads_room
    ON threads(room_id, created_at);

-- Memories table: room memory lookup
CREATE INDEX IF NOT EXISTS idx_memories_room_status
    ON memories(room_id, status);
