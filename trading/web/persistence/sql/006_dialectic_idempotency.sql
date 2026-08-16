-- Stable Dialectic operation keys make prediction create/resolve retries safe.
-- Keys remain internal persistence coordinates and are never returned by the
-- public prediction API.

ALTER TABLE predictions ADD COLUMN source_key TEXT;
ALTER TABLE predictions ADD COLUMN resolution_source_key TEXT;

CREATE UNIQUE INDEX idx_predictions_source_key
    ON predictions(source_key) WHERE source_key IS NOT NULL;
CREATE UNIQUE INDEX idx_predictions_resolution_source_key
    ON predictions(resolution_source_key)
    WHERE resolution_source_key IS NOT NULL;
