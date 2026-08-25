-- 022_geo_scope_lineage.sql — immutable geographic authority and exact lineage

ALTER TABLE geo_scopes
    ADD COLUMN IF NOT EXISTS revision_action TEXT,
    ADD COLUMN IF NOT EXISTS review_note TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'geo_scopes'::regclass
          AND conname = 'geo_scopes_revision_action_check'
    ) THEN
        ALTER TABLE geo_scopes
            ADD CONSTRAINT geo_scopes_revision_action_check
            CHECK (revision_action IS NULL OR revision_action IN (
                'place', 'propose', 'confirm', 'reject', 'redraw',
                'supersede', 'ratify', 'place_signal'
            ));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_scopes_one_successor
    ON geo_scopes (supersedes_id)
    WHERE supersedes_id IS NOT NULL;

CREATE OR REPLACE FUNCTION reject_geo_scope_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'geo_scopes is append-only: % prohibited', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS geo_scopes_reject_update ON geo_scopes;
CREATE TRIGGER geo_scopes_reject_update
    BEFORE UPDATE ON geo_scopes
    FOR EACH ROW EXECUTE FUNCTION reject_geo_scope_mutation();

DROP TRIGGER IF EXISTS geo_scopes_reject_delete ON geo_scopes;
CREATE TRIGGER geo_scopes_reject_delete
    BEFORE DELETE ON geo_scopes
    FOR EACH ROW EXECUTE FUNCTION reject_geo_scope_mutation();
