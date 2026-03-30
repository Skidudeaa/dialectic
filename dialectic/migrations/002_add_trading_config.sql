-- Trading room integration: add trading_config JSONB to rooms
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS trading_config JSONB DEFAULT NULL;
