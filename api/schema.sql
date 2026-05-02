-- StreetHard listing status schema
-- Idempotent: safe to run on every cold start.

CREATE TABLE IF NOT EXISTS listing_status (
    listing_id     TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'none'
                    CHECK (status IN ('none','watching','viewing','shortlisted','rejected','offered')),
    watch          BOOLEAN NOT NULL DEFAULT FALSE,
    notes          TEXT NOT NULL DEFAULT '',
    chips          JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listing_status_updated
    ON listing_status (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_listing_status_status
    ON listing_status (status)
    WHERE status <> 'none';
