-- 028_workshop_jobs.sql — the Workshop's long runs (start_job).
--
-- A row per background run the participant starts in a room's sandbox. The
-- row is the ledger the 60s workshop_job_watch sweep reads: a running row
-- whose process is gone after a restart becomes `lost`; a finished row with
-- reported_at NULL still owes the room its participant turn. Artifacts are
-- ordinary attachments bound to result_message_id by the write_document bind.
CREATE TABLE IF NOT EXISTS workshop_jobs (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    thread_id UUID NOT NULL REFERENCES threads(id),
    label TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('python', 'bash')),
    code TEXT NOT NULL,
    timeout_s INT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'killed', 'lost')),
    pid INT,
    run_dir TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    exit_code INT,
    commit_sha TEXT,
    stdout_tail TEXT,
    stderr_tail TEXT,
    changed_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    killed_by UUID REFERENCES users(id),
    result_message_id UUID REFERENCES messages(id),
    reported_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workshop_jobs_room ON workshop_jobs(room_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workshop_jobs_unreported ON workshop_jobs(finished_at)
    WHERE reported_at IS NULL;
