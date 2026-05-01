-- =============================================================================
-- Harpocrate — Schéma initial
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE users (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keycloak_sub                    TEXT NOT NULL UNIQUE,
    email                           TEXT NOT NULL UNIQUE,
    display_name                    TEXT,

    rsa_public_key                  BYTEA NOT NULL,
    salt_passphrase                 BYTEA NOT NULL,
    salt_recovery                   BYTEA NOT NULL,
    encrypted_rsa_private_key       BYTEA NOT NULL,
    encrypted_sym_key_by_pass       BYTEA NOT NULL,
    encrypted_sym_key_by_recovery   BYTEA NOT NULL,

    kdf_memory_kb                   INTEGER NOT NULL,
    kdf_iterations                  INTEGER NOT NULL,
    kdf_parallelism                 INTEGER NOT NULL,
    rsa_key_size                    INTEGER NOT NULL,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_unlock_at                  TIMESTAMPTZ,

    CONSTRAINT users_kdf_memory_floor CHECK (kdf_memory_kb >= 65536),
    CONSTRAINT users_kdf_iterations_floor CHECK (kdf_iterations >= 3),
    CONSTRAINT users_kdf_parallelism_floor CHECK (kdf_parallelism >= 4),
    CONSTRAINT users_rsa_key_size_valid CHECK (rsa_key_size IN (2048, 4096))
);

CREATE INDEX idx_users_keycloak_sub ON users(keycloak_sub);

-- ─────────────────────────────────────────────────────────────────────────────
-- WALLETS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE wallets (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                            TEXT NOT NULL,
    description                     TEXT,
    owner_user_id                   UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT wallets_name_not_empty CHECK (length(trim(name)) > 0)
);

CREATE INDEX idx_wallets_owner ON wallets(owner_user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- WALLET TAGS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE wallet_tags (
    wallet_id                       UUID NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    tag                             TEXT NOT NULL,

    PRIMARY KEY (wallet_id, tag),
    CONSTRAINT wallet_tags_not_empty CHECK (length(trim(tag)) > 0),
    CONSTRAINT wallet_tags_normalized CHECK (tag = lower(trim(tag)))
);

CREATE INDEX idx_wallet_tags_tag ON wallet_tags(tag);

-- ─────────────────────────────────────────────────────────────────────────────
-- WALLET GRANTS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE wallet_grants (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id                       UUID NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    grantee_user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    encrypted_wallet_key            BYTEA NOT NULL,
    permissions                     SMALLINT NOT NULL,

    granted_by_user_id              UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    granted_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (wallet_id, grantee_user_id),
    CONSTRAINT wallet_grants_permissions_valid CHECK (permissions BETWEEN 0 AND 63),
    CONSTRAINT wallet_grants_permissions_nonzero CHECK (permissions > 0)
);

CREATE INDEX idx_wallet_grants_grantee ON wallet_grants(grantee_user_id);
CREATE INDEX idx_wallet_grants_wallet ON wallet_grants(wallet_id);

-- Trigger : protection du grant de l'owner contre DELETE
CREATE OR REPLACE FUNCTION protect_owner_grant_delete()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM wallets
        WHERE id = OLD.wallet_id AND owner_user_id = OLD.grantee_user_id
    ) THEN
        RAISE EXCEPTION 'Cannot delete grant of wallet owner. Transfer ownership first.'
            USING ERRCODE = '23000';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_protect_owner_grant_delete
    BEFORE DELETE ON wallet_grants
    FOR EACH ROW EXECUTE FUNCTION protect_owner_grant_delete();

-- Trigger : protection du grant de l'owner contre UPDATE des permissions
CREATE OR REPLACE FUNCTION protect_owner_grant_update()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM wallets
        WHERE id = NEW.wallet_id AND owner_user_id = NEW.grantee_user_id
    ) THEN
        IF NEW.permissions <> OLD.permissions THEN
            RAISE EXCEPTION 'Cannot modify permissions of wallet owner.'
                USING ERRCODE = '23000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_protect_owner_grant_update
    BEFORE UPDATE ON wallet_grants
    FOR EACH ROW EXECUTE FUNCTION protect_owner_grant_update();

-- ─────────────────────────────────────────────────────────────────────────────
-- SECRETS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE secrets (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id                       UUID NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    name                            TEXT NOT NULL,
    description                     TEXT,

    encrypted_value                 BYTEA,
    is_placeholder                  BOOLEAN NOT NULL DEFAULT FALSE,

    generation_descriptor           JSONB,
    generation_version              INTEGER NOT NULL DEFAULT 1,
    linked_secret_id                UUID REFERENCES secrets(id) ON DELETE SET NULL,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by_api_key_id           UUID,
    updated_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by_api_key_id           UUID,

    UNIQUE (wallet_id, name),
    CONSTRAINT secrets_name_not_empty CHECK (length(trim(name)) > 0),
    CONSTRAINT secrets_value_or_placeholder CHECK (
        (is_placeholder = TRUE AND encrypted_value IS NULL)
        OR
        (is_placeholder = FALSE AND encrypted_value IS NOT NULL)
    ),
    CONSTRAINT secrets_created_by_one_source CHECK (
        (created_by_user_id IS NOT NULL)::int + (created_by_api_key_id IS NOT NULL)::int = 1
    )
);

CREATE INDEX idx_secrets_wallet ON secrets(wallet_id);
CREATE INDEX idx_secrets_linked ON secrets(linked_secret_id) WHERE linked_secret_id IS NOT NULL;
CREATE INDEX idx_secrets_generation_type ON secrets((generation_descriptor->>'type'))
    WHERE generation_descriptor IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECRET TAGS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE secret_tags (
    secret_id                       UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    tag                             TEXT NOT NULL,

    PRIMARY KEY (secret_id, tag),
    CONSTRAINT secret_tags_not_empty CHECK (length(trim(tag)) > 0),
    CONSTRAINT secret_tags_normalized CHECK (tag = lower(trim(tag)))
);

CREATE INDEX idx_secret_tags_tag ON secret_tags(tag);

-- ─────────────────────────────────────────────────────────────────────────────
-- API KEYS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE api_keys (
    id                                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                                TEXT NOT NULL,
    description                         TEXT,
    wallet_id                           UUID NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    owner_user_id                       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    auth_hash                           BYTEA NOT NULL,
    auth_salt                           BYTEA NOT NULL,
    auth_kdf_memory_kb                  INTEGER NOT NULL,
    auth_kdf_iterations                 INTEGER NOT NULL,
    auth_kdf_parallelism                INTEGER NOT NULL,

    encrypted_wallet_key                BYTEA NOT NULL,
    encrypted_decryption_key_for_owner  BYTEA NOT NULL,

    permissions                         SMALLINT NOT NULL,

    expires_at                          TIMESTAMPTZ,
    revoked_at                          TIMESTAMPTZ,
    last_used_at                        TIMESTAMPTZ,

    created_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT api_keys_permissions_valid CHECK (permissions BETWEEN 0 AND 63),
    CONSTRAINT api_keys_permissions_nonzero CHECK (permissions > 0),
    CONSTRAINT api_keys_kdf_memory_floor CHECK (auth_kdf_memory_kb >= 65536),
    CONSTRAINT api_keys_kdf_iterations_floor CHECK (auth_kdf_iterations >= 3),
    CONSTRAINT api_keys_kdf_parallelism_floor CHECK (auth_kdf_parallelism >= 4),
    CONSTRAINT api_keys_name_not_empty CHECK (length(trim(name)) > 0)
);

CREATE INDEX idx_api_keys_wallet ON api_keys(wallet_id);
CREATE INDEX idx_api_keys_owner ON api_keys(owner_user_id);
CREATE INDEX idx_api_keys_active ON api_keys(id) WHERE revoked_at IS NULL;

-- FK croisée secrets ↔ api_keys (déclarée après création des deux tables)
ALTER TABLE secrets
    ADD CONSTRAINT fk_secrets_created_by_api_key
        FOREIGN KEY (created_by_api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_secrets_updated_by_api_key
        FOREIGN KEY (updated_by_api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- AUDIT LOG
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE audit_log (
    id                              BIGSERIAL PRIMARY KEY,
    occurred_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    actor_user_id                   UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_api_key_id                UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    actor_ip                        INET,

    action                          TEXT NOT NULL,

    target_wallet_id                UUID,
    target_secret_id                UUID,
    target_user_id                  UUID,
    target_api_key_id               UUID,

    metadata                        JSONB,

    success                         BOOLEAN NOT NULL DEFAULT TRUE,
    error_code                      TEXT,

    CONSTRAINT audit_log_one_actor CHECK (
        (actor_user_id IS NOT NULL)::int + (actor_api_key_id IS NOT NULL)::int = 1
    )
);

CREATE INDEX idx_audit_log_occurred_at ON audit_log(occurred_at DESC);
CREATE INDEX idx_audit_log_actor_user ON audit_log(actor_user_id, occurred_at DESC)
    WHERE actor_user_id IS NOT NULL;
CREATE INDEX idx_audit_log_actor_api_key ON audit_log(actor_api_key_id, occurred_at DESC)
    WHERE actor_api_key_id IS NOT NULL;
CREATE INDEX idx_audit_log_target_wallet ON audit_log(target_wallet_id, occurred_at DESC)
    WHERE target_wallet_id IS NOT NULL;
CREATE INDEX idx_audit_log_action ON audit_log(action, occurred_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- updated_at automatique
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_wallets_updated_at BEFORE UPDATE ON wallets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_secrets_updated_at BEFORE UPDATE ON secrets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
