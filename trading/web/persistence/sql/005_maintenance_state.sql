-- 005: maintenance_state — a two-column scratchpad for the retention task.
--
-- WHY a table and not a file: the one fact the daily prune must remember is
-- when VACUUM last ran, and VACUUM is a property of THIS database file. A
-- sidecar file can be copied, restored, or reaped independently of the .db
-- and would then authorise a second full rewrite of a 659 MB file, or
-- suppress one that is overdue. Keeping the timestamp inside the database it
-- describes makes the two impossible to separate.
--
-- Deliberately generic (key/value) rather than one column per fact: the
-- alternative is a migration every time the task learns to remember one
-- more thing, for a table that will hold single-digit rows forever.

CREATE TABLE IF NOT EXISTS maintenance_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
