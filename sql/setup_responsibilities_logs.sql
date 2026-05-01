-- Responsibilities logging table
CREATE TABLE IF NOT EXISTS responsibilities_logs (
    id          BIGSERIAL PRIMARY KEY,
    type        TEXT        NOT NULL,  -- 'interview' or 'ministering'
    target      TEXT        NOT NULL,  -- person/family name
    details     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup by type
CREATE INDEX IF NOT EXISTS responsibilities_logs_type_idx ON responsibilities_logs(type);
