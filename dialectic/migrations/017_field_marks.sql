-- The Field's one table: field_marks. Two row species in mark_kind --
-- 'relation' (an asserted reasoning relationship, inferred or explicit) and
-- 'review' (a human action on a prior mark). Append-only: no code path
-- UPDATEs or DELETEs a row; review state is derived at read time from a
-- mark's own review rows plus successor lineage (field_marks.py). Replacement
-- content from correct/split/merge is written as NEW relation rows (origin
-- 'explicit') in the same transaction, linked by supersedes_id/caused_by_id --
-- never by rewriting the row they replace.
--
-- The partial unique index on (room_id, dedup_key) is the structural
-- guarantee that a corrected mark is never re-asserted: dedup_key uses the
-- SAME formula for an inference candidate and a human's explicit
-- correct/split/merge replacement (field_marks.compute_dedup_key), so once
-- either a human or Dialectic asserts a given {relation, subjects} pair, the
-- row is never deleted and the key stays occupied forever.

CREATE TABLE IF NOT EXISTS field_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(id) ON DELETE SET NULL,  -- NULL = room-wide
    mark_kind TEXT NOT NULL CHECK (mark_kind IN ('relation','review')),
    relation TEXT,   -- §14.3 vocabulary; comment-documented, contract-pinned, no CHECK (the list may grow)
    action TEXT CHECK (action IN ('confirm','contest','correct','supersede','split','merge')),
    origin TEXT CHECK (origin IN ('explicit','inferred')),
    deliberative_status TEXT NOT NULL DEFAULT 'active'
        CHECK (deliberative_status IN ('active','accepted','rejected','resolved','withdrawn')),
    subjects JSONB NOT NULL DEFAULT '[]',  -- array of {entity,id,field} — exactly WorkspaceSourceRef
    target_mark_id UUID REFERENCES field_marks(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}',   -- quote/span, note, merge_group, action extras
    supersedes_id UUID REFERENCES field_marks(id),  -- replacement → what it replaces
    caused_by_id  UUID REFERENCES field_marks(id),  -- replacement → the review row that caused it
    actor_user_id UUID REFERENCES users(id),        -- NULL = Dialectic
    provenance TEXT NOT NULL,                       -- 'field_inference' | 'human'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dedup_key TEXT,                                 -- inference idempotency; set on ALL relation rows, NULL on reviews
    CONSTRAINT relation_iff_relation CHECK ((mark_kind='relation') = (relation IS NOT NULL)),
    CONSTRAINT action_iff_review     CHECK ((mark_kind='review')   = (action   IS NOT NULL)),
    CONSTRAINT review_has_target     CHECK (mark_kind <> 'review' OR target_mark_id IS NOT NULL),
    CONSTRAINT review_has_actor      CHECK (mark_kind <> 'review' OR actor_user_id  IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_field_marks_dedup
    ON field_marks (room_id, dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_field_marks_room     ON field_marks (room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_field_marks_target   ON field_marks (target_mark_id);
CREATE INDEX IF NOT EXISTS idx_field_marks_subjects ON field_marks USING GIN (subjects jsonb_path_ops);

COMMENT ON TABLE field_marks IS
    'The Field: room-local, append-only reasoning marks (inferred + human review). See field_marks.py.';
