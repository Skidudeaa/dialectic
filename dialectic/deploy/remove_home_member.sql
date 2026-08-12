-- remove_home_member.sql
-- Reviewed emergency removal of one Home member. Operator-driven — there is
-- deliberately no removal UI. Deletes ONLY the membership row and appends a
-- home_member_removed event carrying the remover; it never deletes the
-- user, Home, messages, memories, or prior events.
--
-- Run (operator-reviewed emails only):
--   psql "$DATABASE_URL" -v member_email='...' -v removed_by_email='...' \
--        -f deploy/remove_home_member.sql
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE home_member_removal ON COMMIT DROP AS
SELECT
    (SELECT id FROM rooms WHERE is_home) AS home_id,
    (SELECT uc.user_id FROM user_credentials uc
      WHERE lower(uc.email) = lower(trim(:'member_email'))) AS member_id,
    (SELECT uc.user_id FROM user_credentials uc
      WHERE lower(uc.email) = lower(trim(:'removed_by_email'))) AS remover_id;

DO $$
DECLARE
    r RECORD;
    remover_manages BOOLEAN;
    member_manages BOOLEAN;
    manager_count INT;
BEGIN
    SELECT * INTO r FROM home_member_removal;
    IF r.home_id IS NULL THEN
        RAISE EXCEPTION 'Removal requires exactly one Home room';
    END IF;
    IF r.remover_id IS NULL THEN
        RAISE EXCEPTION 'Remover email resolves to no credential identity';
    END IF;
    IF r.member_id IS NULL THEN
        RAISE EXCEPTION 'Member email resolves to no credential identity';
    END IF;

    SELECT can_manage_home INTO remover_manages
    FROM room_memberships
    WHERE room_id = r.home_id AND user_id = r.remover_id;
    IF remover_manages IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'Remover must be a current Home manager';
    END IF;

    SELECT can_manage_home INTO member_manages
    FROM room_memberships
    WHERE room_id = r.home_id AND user_id = r.member_id;
    IF member_manages IS NULL THEN
        RAISE EXCEPTION 'Target is not a current Home member';
    END IF;

    SELECT count(*) INTO manager_count
    FROM room_memberships
    WHERE room_id = r.home_id AND can_manage_home;
    IF member_manages AND manager_count <= 1 THEN
        RAISE EXCEPTION 'Refusing to remove the final Home manager';
    END IF;

    DELETE FROM room_memberships
    WHERE room_id = r.home_id AND user_id = r.member_id;

    INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
    VALUES (gen_random_uuid(), NOW(), 'home_member_removed', r.home_id,
            r.member_id,
            jsonb_build_object('removed_by_user_id', r.remover_id::text));
END $$;

COMMIT;
