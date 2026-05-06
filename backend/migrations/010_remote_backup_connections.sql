-- LOT — Sauvegardes distantes : table de connexions vers des serveurs de backup distants.
--
-- Le contenu de `credentials_encrypted` est un blob :
--   AES-GCM(key_derived_from_HMAC_KEY, json.dumps(credentials_dict))
-- Format binaire : nonce(12B) || ciphertext || tag(16B) — voir app/services/remote_backup_crypto.py
--
-- Le format du dict de credentials dépend de `kind` :
--   kind='sftp'        → {username, auth_method: "password"|"private_key", password?, private_key?, private_key_passphrase?}
--   kind='s3-generic'  → {access_key, secret_key}        (LOT futur)
--   kind='r2'/'b2'/... → idem s3-generic                  (LOT futur)
--
-- Le champ `config` est non-secret (host, port, remote_path, host_key_fingerprint, bucket, region, etc.).

CREATE TABLE remote_backup_connection (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT         NOT NULL,
    kind                  TEXT         NOT NULL CHECK (kind IN ('sftp')),
    config                JSONB        NOT NULL DEFAULT '{}'::jsonb,
    credentials_encrypted BYTEA        NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by_user_id    UUID         REFERENCES users(id) ON DELETE SET NULL,
    deleted_at            TIMESTAMPTZ
);

-- Unicité du nom uniquement parmi les connexions actives (deleted_at IS NULL).
CREATE UNIQUE INDEX idx_remote_backup_connection_name_active
    ON remote_backup_connection (name)
    WHERE deleted_at IS NULL;

-- Lookup rapide des connexions actives.
CREATE INDEX idx_remote_backup_connection_active
    ON remote_backup_connection (kind, created_at DESC)
    WHERE deleted_at IS NULL;

-- Trigger updated_at automatique.
CREATE OR REPLACE FUNCTION trg_remote_backup_connection_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER remote_backup_connection_updated_at
    BEFORE UPDATE ON remote_backup_connection
    FOR EACH ROW
    EXECUTE FUNCTION trg_remote_backup_connection_set_updated_at();
