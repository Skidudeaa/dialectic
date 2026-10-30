-- Ride identity belongs to a shared trip, not any one of its bound rooms.
CREATE TABLE IF NOT EXISTS longway_rides (
    trip_slug TEXT NOT NULL, ride_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'waiting' CHECK (state IN ('waiting','riding','arrived')),
    run_id TEXT, departed_at TIMESTAMPTZ, arrived_at TIMESTAMPTZ,
    departed_pushed BOOLEAN NOT NULL DEFAULT FALSE,
    arrived_pushed BOOLEAN NOT NULL DEFAULT FALSE,
    warned_gaps TEXT[] NOT NULL DEFAULT '{}',
    logbook_written_at TIMESTAMPTZ,
    -- Preserve the last feed before the run disappears, including actual/estimate status.
    stations JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_at TIMESTAMPTZ,
    PRIMARY KEY (trip_slug, ride_id)
);
CREATE TABLE IF NOT EXISTS longway_ride_fixes (
    trip_slug TEXT NOT NULL, ride_id TEXT NOT NULL, at TIMESTAMPTZ NOT NULL,
    lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL,
    speed_mph DOUBLE PRECISION, heading TEXT, km DOUBLE PRECISION, late_min INT,
    source TEXT NOT NULL CHECK (source IN ('amtrak','ais')),
    PRIMARY KEY (trip_slug, ride_id, at),
    FOREIGN KEY (trip_slug, ride_id) REFERENCES longway_rides(trip_slug, ride_id)
);
