-- 007_web_push.sql — Web Push (VAPID) subscriptions for the installed PWA
--
-- WHY a separate table from push_tokens: push_tokens is Expo-shaped (one
-- column, Expo's service). Web Push subscriptions carry an endpoint URL plus
-- two crypto keys and are pruned by HTTP status (404/410) rather than Expo
-- ticket errors. Keeping the channels separate keeps each pruning path honest.

BEGIN;

CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_success_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_push_user ON web_push_subscriptions(user_id);

COMMIT;
