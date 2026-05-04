-- migrations/005_snapshots_policy.sql

ALTER TABLE backups_local
    ADD COLUMN IF NOT EXISTS tier TEXT,
    ADD COLUMN IF NOT EXISTS promoted_from_id UUID REFERENCES backups_local(id) ON DELETE SET NULL;

ALTER TABLE backups_local
    DROP CONSTRAINT IF EXISTS backups_local_filename_format;

ALTER TABLE backups_local
    ADD CONSTRAINT backups_local_filename_format
        CHECK (
            filename ~ '^harpocrate-backup-.*\.tar\.age$'
            OR filename ~ '^harpocrate-snapshot-.*\.tar\.age$'
            OR imported = TRUE
        );

CREATE INDEX IF NOT EXISTS idx_backups_local_tier ON backups_local(tier) WHERE tier IS NOT NULL;

INSERT INTO system_metadata (key, value) VALUES
    ('snapshot_policy', '{
        "interval_minutes": 0,
        "retention": {
            "hourly": 24,
            "daily": 7,
            "weekly": 4,
            "monthly": 12,
            "yearly": 5
        },
        "push_remote_after_snapshot": false,
        "remote_destinations_to_push": [],
        "skip_if_no_change": true
    }'::jsonb)
ON CONFLICT (key) DO NOTHING;
