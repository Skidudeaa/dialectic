-- 029: repo-backed journeys, human-adjudicated evidence, and explicit consent.
-- Review state belongs to field_marks; it is never duplicated on proposals.
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS linked_journey TEXT;
CREATE TABLE IF NOT EXISTS longway_evidence_proposals (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    candidate TEXT NOT NULL, url TEXT NOT NULL, claim TEXT NOT NULL, scope TEXT NOT NULL,
    support TEXT, publisher TEXT, published_at DATE,
    proposed_by TEXT NOT NULL CHECK (proposed_by IN ('llm','human')),
    proposer_user_id UUID REFERENCES users(id),
    source_message_id UUID REFERENCES messages(id),
    written_sid TEXT, written_at TIMESTAMPTZ, written_commit TEXT,
    written_by UUID REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_longway_proposals_room ON longway_evidence_proposals(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_longway_proposals_pending ON longway_evidence_proposals(created_at) WHERE written_at IS NULL;
CREATE TABLE IF NOT EXISTS longway_confirmations (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    member_id UUID NOT NULL REFERENCES users(id),
    binds TEXT NOT NULL, confirmed_on DATE NOT NULL, channel TEXT NOT NULL,
    recorded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_longway_confirmations_room ON longway_confirmations(room_id, created_at);
