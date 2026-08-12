-- Per-user grants for automatic cross-room memory recall.
-- The shared memory row keeps its room scope; each collaborator opts in alone.

CREATE TABLE IF NOT EXISTS user_memory_promotions (
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (memory_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_memory_promotions_user
    ON user_memory_promotions(user_id, memory_id);

COMMENT ON TABLE user_memory_promotions IS
    'Per-user grants for automatic cross-room recall of shared memories';
