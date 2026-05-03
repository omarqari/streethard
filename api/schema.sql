-- StreetHard listing status schema
-- Idempotent: safe to run on every cold start.

CREATE TABLE IF NOT EXISTS listing_status (
    listing_id        TEXT PRIMARY KEY,
    bucket            TEXT NOT NULL DEFAULT 'inbox',
    bucket_changed_at TIMESTAMPTZ,
    price_at_archive  INTEGER,
    oq_notes          TEXT NOT NULL DEFAULT '',
    rq_notes          TEXT NOT NULL DEFAULT '',
    oq_rank           INTEGER,
    rq_rank           INTEGER,
    chips             JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listing_status_updated
    ON listing_status (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_listing_status_bucket
    ON listing_status (bucket);

-- Migration from old schema to three-bucket system.
-- Idempotent: runs on every startup, no-ops when already migrated.
DO $$
DECLARE
    _con text;
BEGIN
    -- If old 'status' column exists, we need to migrate
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listing_status' AND column_name = 'status'
    ) THEN
        -- Add new columns
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'listing_status' AND column_name = 'bucket'
        ) THEN
            ALTER TABLE listing_status ADD COLUMN bucket TEXT NOT NULL DEFAULT 'inbox';
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'listing_status' AND column_name = 'bucket_changed_at'
        ) THEN
            ALTER TABLE listing_status ADD COLUMN bucket_changed_at TIMESTAMPTZ;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'listing_status' AND column_name = 'price_at_archive'
        ) THEN
            ALTER TABLE listing_status ADD COLUMN price_at_archive INTEGER;
        END IF;

        -- Backfill: watched items go to shortlist
        UPDATE listing_status SET bucket = 'shortlist' WHERE watch = true AND bucket = 'inbox';
        -- Set bucket_changed_at from updated_at
        UPDATE listing_status SET bucket_changed_at = updated_at WHERE bucket_changed_at IS NULL;

        -- Drop all CHECK constraints on the table (the old status CHECK blocks DROP COLUMN)
        FOR _con IN
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'listing_status'::regclass AND contype = 'c'
        LOOP
            EXECUTE format('ALTER TABLE listing_status DROP CONSTRAINT %I', _con);
        END LOOP;

        -- Now safe to drop old columns and indexes
        ALTER TABLE listing_status DROP COLUMN IF EXISTS status;
        ALTER TABLE listing_status DROP COLUMN IF EXISTS watch;
        DROP INDEX IF EXISTS idx_listing_status_status;

        -- Re-add the bucket CHECK constraint
        ALTER TABLE listing_status ADD CONSTRAINT listing_status_bucket_check
            CHECK (bucket IN ('inbox', 'shortlist', 'archive'));
    END IF;

    -- Handle legacy 'notes' column rename
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listing_status' AND column_name = 'notes'
    ) THEN
        ALTER TABLE listing_status RENAME COLUMN notes TO oq_notes;
    END IF;

    -- Ensure all expected columns exist (covers fresh DB)
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
