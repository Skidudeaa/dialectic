-- Cross-Session Memory References Migration
-- Enables memories to be referenced and shared across rooms/sessions

-- ============================================================
-- 1. EXTEND MEMORY SCOPE ENUM
-- ============================================================
-- Add GLOBAL scope to existing memories (user-wide, not room-specific)
-- Note: MemoryScope is stored as TEXT, so no ALTER TYPE needed

-- ============================================================
-- 2. MEMORY REFERENCES TABLE
-- ============================================================
-- Tracks when a memory from one room is cited/used in another
CREATE TABLE IF NOT EXISTS memory_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- The memory being referenced (source)
    source_memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    
    -- Where it's being referenced (target)
    target_room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    target_thread_id UUID REFERENCES threads(id) ON DELETE SET NULL,
    target_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    
    -- Who/what made the reference
    referenced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    referenced_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    referenced_by_llm BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Context for why this was referenced
    citation_context TEXT,  -- e.g., "User asked about previous discussion on free will"
    relevance_score FLOAT,  -- Semantic similarity score when auto-suggested
    
    -- Prevent duplicate references in same message
    UNIQUE (source_memory_id, target_message_id)
);

CREATE INDEX idx_memory_refs_source ON memory_references(source_memory_id);
CREATE INDEX idx_memory_refs_target_room ON memory_references(target_room_id);
CREATE INDEX idx_memory_refs_target_message ON memory_references(target_message_id);

-- ============================================================
-- 3. USER MEMORY COLLECTIONS
-- ============================================================
-- Allow users to organize memories into collections that persist across rooms
CREATE TABLE IF NOT EXISTS user_memory_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- If true, memories in this collection are auto-injected into all user's rooms
    auto_inject BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Ordering for display
    display_order INT NOT NULL DEFAULT 0,
    
    UNIQUE (user_id, name)
);

CREATE INDEX idx_collections_user ON user_memory_collections(user_id);

-- ============================================================
-- 4. COLLECTION MEMBERSHIP
-- ============================================================
-- Links memories to collections (many-to-many)
CREATE TABLE IF NOT EXISTS collection_memories (
    collection_id UUID NOT NULL REFERENCES user_memory_collections(id) ON DELETE CASCADE,
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    notes TEXT,  -- User notes about why this memory is in collection
    PRIMARY KEY (collection_id, memory_id)
);

CREATE INDEX idx_collection_memories_memory ON collection_memories(memory_id);

-- ============================================================
-- 5. GLOBAL MEMORIES VIEW
-- ============================================================
-- Convenience view for querying all memories accessible to a user
CREATE OR REPLACE VIEW user_accessible_memories AS
SELECT 
    m.*,
    r.id as room_id,
    rm.user_id as accessor_user_id,
    CASE 
        WHEN m.scope = 'global' THEN true
        WHEN m.scope = 'user' AND m.owner_user_id = rm.user_id THEN true
        WHEN m.scope = 'room' THEN true
        ELSE false
    END as is_accessible,
    CASE
        WHEN m.room_id = r.id THEN 'local'
        ELSE 'cross_room'
    END as memory_source
FROM memories m
JOIN rooms r ON m.room_id = r.id OR m.scope = 'global'
JOIN room_memberships rm ON r.id = rm.room_id
WHERE m.status = 'active';

-- ============================================================
-- 6. ADD GLOBAL SCOPE SUPPORT TO EXISTING MEMORIES
-- ============================================================
-- Add column to track if memory has been promoted to global
ALTER TABLE memories ADD COLUMN IF NOT EXISTS promoted_to_global_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS promoted_by_user_id UUID REFERENCES users(id);

-- ============================================================
-- 7. EVENT TYPES FOR CROSS-SESSION OPERATIONS
-- ============================================================
-- These will be added to the EventType enum in models.py:
-- - MEMORY_PROMOTED (room -> global)
-- - MEMORY_REFERENCED (cited in another room)
-- - COLLECTION_CREATED
-- - COLLECTION_MEMORY_ADDED
-- - COLLECTION_MEMORY_REMOVED

COMMENT ON TABLE memory_references IS 'Tracks citations of memories across rooms/sessions';
COMMENT ON TABLE user_memory_collections IS 'User-defined collections of memories that persist across rooms';
COMMENT ON TABLE collection_memories IS 'Many-to-many link between collections and memories';
