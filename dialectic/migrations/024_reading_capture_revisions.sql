-- 024: immutable evidence for direct Safari captures. reading_items remains the
-- current searchable projection; every browser body is retained here exactly.

ALTER TABLE reading_items
    ADD COLUMN IF NOT EXISTS current_revision_id UUID,
    ADD COLUMN IF NOT EXISTS current_captured_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS content_sha256 TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reading_items_id_room_unique'
          AND conrelid = 'reading_items'::regclass
    ) THEN
        ALTER TABLE reading_items
            ADD CONSTRAINT reading_items_id_room_unique UNIQUE (id, room_id);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS reading_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reading_id UUID NOT NULL REFERENCES reading_items(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    capture_id UUID NOT NULL UNIQUE,
    captured_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    source_url TEXT NOT NULL CHECK (length(source_url) > 0),
    capture_mode TEXT NOT NULL
        CHECK (capture_mode IN ('selection', 'article', 'page_fallback')),
    content TEXT NOT NULL CHECK (length(content) > 0),
    content_sha256 TEXT NOT NULL
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL DEFAULT '{}'
        CHECK (jsonb_typeof(metadata) = 'object'),
    captured_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- CREATE TABLE IF NOT EXISTS does not repair an earlier draft of this
-- migration. Reassert the wall-clock default explicitly.
ALTER TABLE reading_revisions
    ALTER COLUMN received_at SET DEFAULT clock_timestamp();

CREATE OR REPLACE FUNCTION reject_reading_revision_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'reading revisions are immutable';
END
$$;

DROP TRIGGER IF EXISTS trg_reading_revisions_immutable ON reading_revisions;
CREATE TRIGGER trg_reading_revisions_immutable
    BEFORE UPDATE ON reading_revisions
    FOR EACH ROW EXECUTE FUNCTION reject_reading_revision_update();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reading_revisions_reading_room_fk'
          AND conrelid = 'reading_revisions'::regclass
    ) THEN
        ALTER TABLE reading_revisions
            ADD CONSTRAINT reading_revisions_reading_room_fk
            FOREIGN KEY (reading_id, room_id)
            REFERENCES reading_items(id, room_id)
            ON DELETE CASCADE;
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION validate_reading_current_revision()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.current_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM reading_revisions revision
        WHERE revision.id = NEW.current_revision_id
          AND revision.reading_id = NEW.id
          AND revision.room_id = NEW.room_id
    ) THEN
        RAISE EXCEPTION 'current revision must belong to the same reading and room';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_reading_items_current_revision ON reading_items;
CREATE TRIGGER trg_reading_items_current_revision
    AFTER INSERT OR UPDATE ON reading_items
    FOR EACH ROW EXECUTE FUNCTION validate_reading_current_revision();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reading_items_current_revision_fk'
          AND conrelid = 'reading_items'::regclass
    ) THEN
        ALTER TABLE reading_items
            ADD CONSTRAINT reading_items_current_revision_fk
            FOREIGN KEY (current_revision_id)
            REFERENCES reading_revisions(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reading_items_content_sha256_format'
          AND conrelid = 'reading_items'::regclass
    ) THEN
        ALTER TABLE reading_items
            ADD CONSTRAINT reading_items_content_sha256_format
            CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_reading_revisions_reading
    ON reading_revisions (reading_id, captured_at DESC, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_reading_revisions_room
    ON reading_revisions (room_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_reading_items_effective_freshness
    ON reading_items (
        room_id,
        (COALESCE(current_captured_at, created_at)) DESC,
        id DESC
    );

COMMENT ON TABLE reading_items IS
    'Logical room readings; source includes proposal, human, wire, night_shift, deep_dive, newsletter, congress, and browser_capture';
COMMENT ON TABLE reading_revisions IS
    'Immutable exact Markdown snapshots from direct human browser captures';
