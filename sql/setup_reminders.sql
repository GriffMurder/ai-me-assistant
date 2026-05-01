-- Reminders table
CREATE TABLE IF NOT EXISTS reminders (
    id         BIGSERIAL PRIMARY KEY,
    task       TEXT        NOT NULL,
    remind_at  TIMESTAMPTZ NOT NULL,
    fired      BOOLEAN     DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Partial index for efficient polling of unfired reminders
CREATE INDEX IF NOT EXISTS reminders_unfired_idx ON reminders(remind_at) WHERE NOT fired;
