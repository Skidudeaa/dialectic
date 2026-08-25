-- 021_geo_scopes.sql — the World Lens substrate: geography attached to rows
-- that already exist.
--
-- ARCHITECTURE (docs/WORLD_LENS_VISION.md): before this migration nothing in
-- Dialectic carried a coordinate — no column on readings, memories, marks or
-- Atlas nodes. A globe had nothing to place. Rather than a lat/lon column per
-- table (or a universal artifact table, which the workroom rule forbids),
-- geometry lives in ONE table and points at its subject through the same
-- {entity, id, field} ref that field_marks.subjects and
-- workspace_objects.source_entity already use.
--
-- AUTHORITY IS A COLUMN, NOT A STYLE. `machine_proposed` geometry is what the
-- participant may write (llm tool); it renders provisional and cannot be a
-- Field-mark subject until a human confirms it (field_marks.py's subject
-- allowlist carries that predicate). `human_confirmed` is a person's act,
-- stamped in the same row (confirmed_by/confirmed_at) — never "by nobody".
-- `source_reported` is an adapter's fix (a vessel, a quake) that a human
-- placed or marked and so became evidence.
--
-- APPEND-ONLY with supersession, the field_marks/memories pattern: confirming
-- a proposal INSERTS a human_confirmed row naming the proposal in
-- supersedes_id; rejecting one INSERTS a human_confirmed row whose
-- source_state is 'confirmed_empty' ("a person looked; it is not there").
-- The live set is derived at read time (geo_scopes.py: not expired, not
-- superseded, not confirmed_empty). No UPDATE, no DELETE.
CREATE TABLE IF NOT EXISTS geo_scopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    subject JSONB NOT NULL,                 -- {entity,id,field}: rooms | reading_items | field_marks | messages | memories
    kind TEXT NOT NULL CHECK (kind IN ('point','route','polygon','region')),
    geometry JSONB NOT NULL,                -- GeoJSON geometry, [lon,lat] positions
    label TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL CHECK (authority IN ('human_confirmed','source_reported','machine_proposed')),
    provenance JSONB NOT NULL,              -- {provider, source_id?, url?, acquisition, credit}
    observed_at TIMESTAMPTZ,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    source_state TEXT NOT NULL DEFAULT 'ok'
        CHECK (source_state IN ('ok','partial','confirmed_empty','stale','unavailable','rate_limited','not_configured')),
    confirmed_by UUID REFERENCES users(id),
    confirmed_at TIMESTAMPTZ,
    supersedes_id UUID REFERENCES geo_scopes(id),
    created_by UUID REFERENCES users(id),   -- NULL = Dialectic
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT confirmed_iff_human CHECK ((authority = 'human_confirmed') = (confirmed_by IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_geo_scopes_room       ON geo_scopes (room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_geo_scopes_subject    ON geo_scopes USING GIN (subject jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_geo_scopes_supersedes ON geo_scopes (supersedes_id);
COMMENT ON TABLE geo_scopes IS
    'World Lens: append-only geography attached to existing rows, with authority and provenance. See geo_scopes.py.';
