-- Reviewed operator script — never run automatically, matches this repo's
-- own convention (see deploy/activate_home_founders.sql,
-- deploy/remove_home_member.sql).
--
-- Removes 7 confirmed-inert, zero-member rooms found while closing the
-- 2026-08-24 UX audit loops (docs/reviews/2026-08-24_ux-shortcomings-review.md).
-- All 7 have zero room_memberships (nobody can reach them through any normal
-- flow) and were checked individually before listing here:
--   T1, T123, T123sdfasdfsd        — 2026-02-17 dev/test debris
--   '; DROP TABLE rooms; --'       — 2026-02-14, zero messages, an inert
--                                     SQL-injection PAYLOAD string stored as
--                                     a room name. Parameterized queries ate
--                                     it harmlessly — this confirms room
--                                     creation is NOT vulnerable — but
--                                     something/someone did probe it once.
--   firstRoom! (x2, duplicate)     — 2026-06-10 onboarding-flow test debris
--   probe-do-not-create            — 2026-08-13, the human-interaction-audit's
--                                     own test artifact, self-labeled
--
-- Deliberately NOT included: Trump Tariffs Trading Room (8adcabb7-...) — a
-- live bound trading book, not debris. See backfill_trump_tariffs.py in the
-- same session's scratchpad — it needs members added, not deletion.
--
-- Run manually after a final look, e.g.:
--   psql "$DATABASE_URL" -f deploy/cleanup_orphaned_test_rooms.sql
-- Each DELETE cascades however this schema's FKs are defined for
-- threads/messages/events under a room — check `\d rooms` for ON DELETE
-- behavior before running against production if that matters to you; all 7
-- rooms have zero messages besides the injection-payload one (verify with
-- the SELECT below), so cascade blast radius should be zero either way.

-- Verify before deleting: confirm all 7 still have no messages/members.
SELECT r.id, r.name, r.created_at,
       (SELECT count(*) FROM room_memberships WHERE room_id = r.id) AS members,
       (SELECT count(*) FROM threads t JOIN messages m ON m.thread_id = t.id WHERE t.room_id = r.id) AS messages
FROM rooms r
WHERE r.id IN (
    SELECT r2.id FROM rooms r2
    LEFT JOIN room_memberships rm ON rm.room_id = r2.id
    WHERE rm.room_id IS NULL AND r2.id <> '8adcabb7-817a-4802-87c6-3bfd42e6a9eb'
);

-- Uncomment to actually delete, after reviewing the SELECT above:
-- DELETE FROM rooms
-- WHERE id IN (
--     SELECT r2.id FROM rooms r2
--     LEFT JOIN room_memberships rm ON rm.room_id = r2.id
--     WHERE rm.room_id IS NULL AND r2.id <> '8adcabb7-817a-4802-87c6-3bfd42e6a9eb'
-- );
