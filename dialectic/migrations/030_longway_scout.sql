-- 030: questions, durable research receipts and source-backed proposals.
CREATE TABLE IF NOT EXISTS longway_questions (
  id UUID PRIMARY KEY, room_id UUID NOT NULL REFERENCES rooms(id), journey TEXT NOT NULL, text TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('human','reaction','message','dossier','scout')),
  source_message_id UUID REFERENCES messages(id), asked_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  answered_by_proposal UUID REFERENCES longway_evidence_proposals(id), closed_at TIMESTAMPTZ, closed_by UUID REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS longway_scout_runs (
  id UUID PRIMARY KEY, room_id UUID NOT NULL REFERENCES rooms(id), journey TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('manual','nightly')), started_by UUID REFERENCES users(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running','done','failed','killed')),
  questions UUID[] NOT NULL DEFAULT '{}', pages_read INT NOT NULL DEFAULT 0, searches INT NOT NULL DEFAULT 0,
  proposals INT NOT NULL DEFAULT 0, counter_proposals INT NOT NULL DEFAULT 0,
  input_tokens INT NOT NULL DEFAULT 0, output_tokens INT NOT NULL DEFAULT 0, error TEXT, log JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE IF NOT EXISTS longway_search_results (
  id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES longway_scout_runs(id), provider TEXT NOT NULL, query TEXT NOT NULL,
  rank INT NOT NULL, url TEXT NOT NULL, title TEXT, snippet TEXT, retrieved_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE longway_evidence_proposals
  ADD COLUMN IF NOT EXISTS question_id UUID REFERENCES longway_questions(id),
  ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES longway_scout_runs(id),
  ADD COLUMN IF NOT EXISTS search_result_id UUID REFERENCES longway_search_results(id),
  ADD COLUMN IF NOT EXISTS contradicts UUID REFERENCES longway_evidence_proposals(id),
  ADD COLUMN IF NOT EXISTS applies_from DATE, ADD COLUMN IF NOT EXISTS applies_to DATE, ADD COLUMN IF NOT EXISTS direction TEXT, ADD COLUMN IF NOT EXISTS passport TEXT, ADD COLUMN IF NOT EXISTS vehicle TEXT,
  ADD COLUMN IF NOT EXISTS leg_from TEXT, ADD COLUMN IF NOT EXISTS leg_to TEXT,
  ADD COLUMN IF NOT EXISTS load_bearing BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS counter_searched_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS publisher_count INT;

-- The database owns exclusivity, including across backend processes.
CREATE UNIQUE INDEX IF NOT EXISTS longway_one_running_journey
    ON longway_scout_runs(journey) WHERE status='running';
CREATE UNIQUE INDEX IF NOT EXISTS longway_question_text
    ON longway_questions(journey, text);
CREATE INDEX IF NOT EXISTS longway_questions_open
    ON longway_questions(journey, created_at) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS longway_runs_room ON longway_scout_runs(room_id, started_at DESC);
CREATE INDEX IF NOT EXISTS longway_results_run ON longway_search_results(run_id);
