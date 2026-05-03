-- migrations/004_backup_tables.sql

CREATE TABLE backups_local (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename            TEXT NOT NULL UNIQUE,
    size_bytes          BIGINT NOT NULL,
    checksum_sha256     TEXT NOT NULL,
    age_recipient       TEXT NOT NULL,
    manifest            JSONB NOT NULL,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    imported            BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT backups_local_filename_format
        CHECK (filename ~ '^harpocrate-backup-.*\.tar\.age$' OR imported = TRUE)
);

CREATE INDEX idx_backups_local_created_at ON backups_local(created_at DESC);

CREATE TABLE system_metadata (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO system_metadata (key, value) VALUES
    ('maintenance_mode', '{"active": false, "reason": null, "started_at": null, "effective_at": null, "estimated_end_at": null}'::jsonb),
    ('last_restored_at', 'null'::jsonb),
    ('last_backup_at', 'null'::jsonb);
