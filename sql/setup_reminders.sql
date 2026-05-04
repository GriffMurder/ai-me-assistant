-- Reminders table
CREATE TABLE IF NOT EXISTS reminders (
    id               BIGSERIAL PRIMARY KEY,
    task             TEXT        NOT NULL,
    remind_at        TIMESTAMPTZ NOT NULL,
    fired            BOOLEAN     DEFAULT FALSE,
    fired_at         TIMESTAMPTZ,
    delivery_status  TEXT        DEFAULT 'pending',  -- pending | sent | failed
    delivery_error   TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Partial index for efficient polling of unfired reminders
CREATE INDEX IF NOT EXISTS reminders_unfired_idx ON reminders(remind_at) WHERE NOT fired;

-- Migration: add delivery tracking columns if upgrading an existing table
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS fired_at        TIMESTAMPTZ;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS delivery_status TEXT DEFAULT 'pending';
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS delivery_error  TEXT;
