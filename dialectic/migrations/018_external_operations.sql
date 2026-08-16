-- Durable leases for writes that cross from Dialectic into another service.
-- The operation key and optional message coordinate are stable across retries;
-- a short pending lease prevents concurrent owners while failed/expired work
-- remains reclaimable.

CREATE TABLE IF NOT EXISTS external_operations (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    operation_kind TEXT NOT NULL,
    operation_key TEXT NOT NULL UNIQUE,
    initiated_by_user_id UUID NOT NULL REFERENCES users(id),
    source_message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
    proposal_slot TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    external_result JSONB,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((source_message_id IS NULL) = (proposal_slot IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_operations_message_slot
    ON external_operations(source_message_id, proposal_slot)
    WHERE source_message_id IS NOT NULL AND proposal_slot IS NOT NULL;
