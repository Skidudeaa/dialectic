-- 013_home_base.sql
-- The singleton Home room: one real, unbound room with one root thread
-- named 'Main'. A partial unique index enforces the singleton in PostgreSQL;
-- one additive boolean (no room-kind enum) keeps every existing rooms
-- consumer working unchanged. Bootstrap creates Home + Main + their events
-- idempotently and adds NO memberships — founder activation is a separately
-- reviewed transaction (deploy/activate_home_founders.sql).

ALTER TABLE rooms
    ADD COLUMN IF NOT EXISTS is_home BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_single_home
    ON rooms (is_home)
    WHERE is_home;

ALTER TABLE room_memberships
    ADD COLUMN IF NOT EXISTS can_manage_home BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
DECLARE
    home_id UUID;
    main_id UUID;
    created_home BOOLEAN := FALSE;
    created_main BOOLEAN := FALSE;
BEGIN
    SELECT id INTO home_id FROM rooms WHERE is_home;
    IF home_id IS NULL THEN
        home_id := gen_random_uuid();
        INSERT INTO rooms (id, created_at, token, name, is_home)
        VALUES (
            home_id,
            NOW(),
            replace(gen_random_uuid()::text, '-', ''),
            'Home',
            TRUE
        );
        created_home := TRUE;
    END IF;

    SELECT id INTO main_id
    FROM threads
    WHERE room_id = home_id AND parent_thread_id IS NULL
    ORDER BY created_at, id
    LIMIT 1;

    IF main_id IS NULL THEN
        main_id := gen_random_uuid();
        INSERT INTO threads (id, room_id, created_at, title)
        VALUES (main_id, home_id, NOW(), 'Main');
        created_main := TRUE;
    END IF;

    IF created_home THEN
        INSERT INTO events (id, timestamp, event_type, room_id, payload)
        VALUES (gen_random_uuid(), NOW(), 'room_created', home_id,
                jsonb_build_object('name', 'Home'));
    END IF;

    IF created_main THEN
        INSERT INTO events
            (id, timestamp, event_type, room_id, thread_id, payload)
        VALUES (gen_random_uuid(), NOW(), 'thread_created', home_id, main_id,
                jsonb_build_object('title', 'Main'));
    END IF;
END $$;
