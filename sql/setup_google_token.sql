-- Stores the single Google OAuth token blob so it survives Render redeploys.
-- Run once in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS google_token (
    id INT PRIMARY KEY DEFAULT 1,
    token_json TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);

NOTIFY pgrst, 'reload schema';
