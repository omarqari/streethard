-- StreetHard listing status schema
-- Idempotent: safe to run on every cold start.

CREATE TABLE IF NOT EXISTS listing_status (
    listing_id     TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'none'
                    CHECK (status IN ('none','watching','viewing','shortlisted','rejected','offered')),
    watch          BOOLEAN NOT NULL DEFAULT FALSE,
    oq_notes       TEXT NOT NULL DEFAULT '',
    rq_notes       TEXT NOT NULL DEFAULT '',
    oq_rank        INTEGER,
    rq_rank        INTEGER,
    chips          JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listing_status_updated
    ON listing_status (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_listing_status_status
    ON listing_status (status)
    WHERE status <> 'none';

-- Migration: rename legacy "notes" column → "oq_notes" if it exists.
-- This DO block is idempotent — runs on every startup, no-ops when already migrated.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listing_status' AND column_name = 'notes'
    ) THEN
        ALTER TABLE listing_status RENAME COLUMN notes TO oq_notes;
    END IF;

    -- Add new columns if they don't exist yet (covers fresh DB and migration).
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listing_status' AND column_name = 'rq_notes'
    ) THEN
        ALTER TABLE listing_status ADD COLUMN rq_notes TEXT NOT NULL DEFAULT '';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listing_status' AND column_name = 'oq_rank'
    ) THEN
        ALTER TABLE listing_status ADD COLUMN oq_rank INTEGER;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listing_status' AND column_name = 'rq_rank'
    ) THEN
        ALTER TABLE listing_status ADD COLUMN rq_rank INTEGER;
    END IF;
END $$;
