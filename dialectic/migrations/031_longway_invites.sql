-- 031: asking for a seat. A stranger's request to join the house, the planner's decision, and the invite it produced.
CREATE TABLE IF NOT EXISTS longway_invite_requests (
  id UUID PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', ip TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  notified_at TIMESTAMPTZ,
  decision TEXT CHECK (decision IN ('invited','declined')), decided_at TIMESTAMPTZ, decided_by UUID REFERENCES users(id),
  user_id UUID REFERENCES users(id), invited_email_at TIMESTAMPTZ
);
-- One open request per address: asking twice refreshes the first instead of stacking a second.
CREATE UNIQUE INDEX IF NOT EXISTS idx_longway_invite_requests_open ON longway_invite_requests(email) WHERE decision IS NULL;
CREATE INDEX IF NOT EXISTS idx_longway_invite_requests_unnotified ON longway_invite_requests(created_at) WHERE notified_at IS NULL AND decision IS NULL;
