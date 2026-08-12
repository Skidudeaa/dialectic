-- activate_home_founders.sql
-- Reviewed, parameterized founder activation for the Home room. Resolves
-- exactly Amo and Dan by normalized credential email — never by any other
-- attribute, never by backfilling all credentialed accounts. Aborts unless
-- each email resolves to exactly one distinct credential identity and
-- exactly one Home room exists.
--
-- Run (operator-reviewed emails only):
--   psql "$DATABASE_URL" -v amo_email='...' -v dan_email='...' \
--        -f deploy/activate_home_founders.sql
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE home_founder_activation (
    email TEXT PRIMARY KEY,
    user_id UUID
) ON COMMIT DROP;

INSERT INTO home_founder_activation (email, user_id)
SELECT requested.email, uc.user_id
FROM (
    VALUES (lower(trim(:'amo_email'))), (lower(trim(:'dan_email')))
) AS requested(email)
JOIN user_credentials uc ON lower(uc.email) = requested.email;

DO $$
BEGIN
    IF (SELECT count(*) FROM home_founder_activation) <> 2
       OR (SELECT count(DISTINCT user_id) FROM home_founder_activation) <> 2 THEN
        RAISE EXCEPTION 'Founder activation requires exactly two distinct credential identities';
    END IF;
    IF (SELECT count(*) FROM rooms WHERE is_home) <> 1 THEN
        RAISE EXCEPTION 'Founder activation requires exactly one Home room';
    END IF;
END $$;

WITH home AS (
    SELECT id FROM rooms WHERE is_home
), added AS (
    INSERT INTO room_memberships
        (room_id, user_id, joined_at, can_manage_home)
    SELECT home.id, founder.user_id, NOW(), TRUE
    FROM home CROSS JOIN home_founder_activation founder
    ON CONFLICT (room_id, user_id) DO UPDATE
        SET can_manage_home = TRUE
    WHERE NOT room_memberships.can_manage_home
    RETURNING room_id, user_id
)
INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
SELECT gen_random_uuid(), NOW(), 'user_joined', room_id, user_id,
       jsonb_build_object('activation', 'home_founder')
FROM added
WHERE NOT EXISTS (
    SELECT 1 FROM events e
    WHERE e.event_type = 'user_joined'
      AND e.room_id = added.room_id
      AND e.user_id = added.user_id
);

COMMIT;
