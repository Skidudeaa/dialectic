-- Record WHY a session was revoked, so an evicted device can explain itself.
--
-- Sessions were revoked for three different reasons (user logout, the
-- multi-device limit evicting the least-recently-used session, and a
-- password reset revoking everything) and all three looked identical to the
-- client: /auth/refresh returned a flat 401 and the app dropped to a blank
-- auth screen. NULL means "revoked before this column existed" or "still
-- active"; callers must treat an unknown/absent reason as a plain expiry.
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS revoked_reason TEXT;
