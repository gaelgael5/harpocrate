# Lot 01 — Schéma DB complet

> **Prérequis** : `LOT_00_FOUNDATIONS.md` terminé.

## Objectif

Créer **toutes les tables métier d'Harpocrate** en une seule migration cohérente : `users`, `user_external_identities`, `identity_anomaly_events`, `wallets`, `wallet_tags`, `wallet_grants`, `secrets`, `secret_tags`, `api_keys`, `audit_log`. Avec les contraintes, triggers, et index.

## Dépendances

- Lot 00

## Périmètre

### Inclus

- Migration SQL `001_schema_initial.sql` complète
- Trigger `protect_owner_grant` (DELETE + UPDATE)
- Trigger `set_updated_at` sur les tables avec `updated_at`
- Tables d'identité externes et événements d'anomalie
- Tables de quarantaine (colonnes sur `users`)
- Script de seed `migrations/seed_dev.sql`
- Tests d'intégrité du schéma

### Exclus

- Aucune API métier
- Pas de modèles Pydantic des entités

## Spécifications fonctionnelles

### Règles métier matérialisées en DB

1. **Owner immutable** : `wallet_grants` du grantee = owner ne peut être supprimé ni modifié sauf via transfert d'ownership
2. **Permissions ⊆ 0..63** : CHECK constraints
3. **Permissions > 0** : grant inutile interdit
4. **Secret unique par (wallet, name)** : UNIQUE constraint
5. **Placeholder vs valorisé** : `is_placeholder=TRUE ⟺ encrypted_value IS NULL`
6. **Tags normalisés** : lowercase, trimmed
7. **Owner non supprimable** : ON DELETE RESTRICT
8. **API keys** : permissions ⊆ 0..63, paramètres KDF ≥ floors
9. **Audit log** : exactement un acteur (user XOR api_key)
10. **External identity** : (provider, external_subject) UNIQUE globalement
11. **Une seule primary identity par user**
12. **Anomalies catégorisées** : severity ∈ {info, warning, critical}

## Spécifications techniques

### Fichier `migrations/001_schema_initial.sql`

```sql
-- =============================================================================
-- Harpocrate — Schéma initial
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE users (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                           TEXT NOT NULL UNIQUE,
    display_name                    TEXT,

    -- Crypto E2E
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

    -- Identity governance
    quarantine_until                TIMESTAMPTZ,
    quarantine_reason               TEXT,
    force_reverify_next_login       BOOLEAN NOT NULL DEFAULT FALSE,
    disabled_at                     TIMESTAMPTZ,
    disabled_reason                 TEXT,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_unlock_at                  TIMESTAMPTZ,

    CONSTRAINT users_kdf_memory_floor CHECK (kdf_memory_kb >= 65536),
    CONSTRAINT users_kdf_iterations_floor CHECK (kdf_iterations >= 3),
    CONSTRAINT users_kdf_parallelism_floor CHECK (kdf_parallelism >= 4),
    CONSTRAINT users_rsa_key_size_valid CHECK (rsa_key_size IN (2048, 4096))
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_quarantine ON users(quarantine_until)
    WHERE quarantine_until IS NOT NULL;
CREATE INDEX idx_users_disabled ON users(disabled_at) WHERE disabled_at IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- USER EXTERNAL IDENTITIES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE user_external_identities (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider                        TEXT NOT NULL,
    external_subject                TEXT NOT NULL,
    is_primary                      BOOLEAN NOT NULL DEFAULT FALSE,
    linked_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at                   TIMESTAMPTZ,

    -- Snapshot au moment du linking, pour détecter les anomalies
    linked_email                    TEXT,
    linked_display_name             TEXT,

    UNIQUE (provider, external_subject),
    CONSTRAINT user_ext_provider_valid
        CHECK (provider IN ('google', 'github', 'microsoft', 'apple', 'keycloak_internal'))
);

CREATE INDEX idx_user_external_user ON user_external_identities(user_id);
CREATE INDEX idx_user_external_lookup
    ON user_external_identities(provider, external_subject);

-- Une seule primary par user
CREATE UNIQUE INDEX idx_user_external_one_primary
    ON user_external_identities(user_id) WHERE is_primary = TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- IDENTITY ANOMALY EVENTS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE identity_anomaly_events (
    id                              BIGSERIAL PRIMARY KEY,
    user_id                         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    detected_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity                        TEXT NOT NULL,
    anomaly_type                    TEXT NOT NULL,
    metadata                        JSONB,
    acknowledged_at                 TIMESTAMPTZ,
    acknowledged_by_user_id         UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT identity_anomaly_severity_valid
        CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX idx_identity_anomaly_user ON identity_anomaly_events(user_id, detected_at DESC);
CREATE INDEX idx_identity_anomaly_unack
    ON identity_anomaly_events(user_id) WHERE acknowledged_at IS NULL;

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

-- FK croisée secrets ↔ api_keys
ALTER TABLE secrets
    ADD CONSTRAINT fk_secrets_created_by_api_key
        FOREIGN KEY (created_by_api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_secrets_updated_by_api_key
        FOREIGN KEY (updated_by_api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- REVERIFY TOKENS (preuves de re-vérification de passphrase)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE reverify_tokens (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash                      BYTEA NOT NULL,
    issued_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at                      TIMESTAMPTZ NOT NULL,
    consumed_at                     TIMESTAMPTZ,

    CONSTRAINT reverify_expires_after_issued CHECK (expires_at > issued_at)
);

CREATE INDEX idx_reverify_user_active ON reverify_tokens(user_id, expires_at)
    WHERE consumed_at IS NULL;

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
-- SERVER SESSION EPOCH (pour invalider toutes les sessions après un restore)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE server_session_epoch (
    id                              INTEGER PRIMARY KEY DEFAULT 1,
    epoch                           BIGINT NOT NULL DEFAULT 1,
    rotated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_reason                  TEXT,

    CONSTRAINT server_session_epoch_singleton CHECK (id = 1)
);

INSERT INTO server_session_epoch (id, epoch, rotated_reason) VALUES (1, 1, 'initial');

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
```

### Tests d'intégration (extraits)

```python
async def test_owner_grant_protected_from_delete(db_pool):
    # Créer user, wallet, grant owner, tenter delete → exception
    ...

async def test_one_primary_identity_per_user(db_pool):
    """Tenter d'avoir 2 primary pour le même user → contrainte UNIQUE"""
    # Créer user, identity1 primary, identity2 primary → UniqueViolation
    ...

async def test_external_subject_unique_globally(db_pool):
    """Le même (provider, sub) ne peut pas être lié à 2 users différents"""
    ...

async def test_quarantine_columns_nullable(db_pool):
    """quarantine_until et quarantine_reason peuvent être NULL"""
    ...

async def test_anomaly_severity_check(db_pool):
    """severity invalide → CheckViolation"""
    ...

async def test_server_session_epoch_singleton(db_pool):
    """Tenter d'insérer un 2e row dans server_session_epoch → erreur"""
    ...

async def test_secret_placeholder_must_have_null_value(db_pool):
    """is_placeholder=TRUE force encrypted_value=NULL"""
    ...

async def test_audit_log_requires_exactly_one_actor(db_pool):
    """0 ou 2 acteurs rejeté"""
    ...

async def test_permissions_bitmap_range(db_pool):
    """permissions > 63 → CheckViolation"""
    ...
```

## Critères de succès

1. ✅ Migration applique sans erreur
2. ✅ Toutes les tables créées (15 tables)
3. ✅ Tous les triggers actifs
4. ✅ Tous les index créés
5. ✅ `server_session_epoch` initialisé avec epoch=1
6. ✅ Test trigger owner protection (DELETE et UPDATE)
7. ✅ Test one-primary-identity-per-user
8. ✅ Test external_subject unique global
9. ✅ Test severity anomaly CHECK
10. ✅ Re-jouer la migration deux fois → no-op
11. ✅ Modifier le contenu de la migration → erreur de checksum

## Pièges connus

- **`user_external_identities` UNIQUE global** : un même `(provider, sub)` ne peut être lié qu'à un seul user. Sinon deux users avec le même compte Google.
- **`is_primary` UNIQUE partial index** : seuls les TRUE sont uniques par user. Permet d'avoir 0 primary (cas transitoire) ou 1 primary.
- **`server_session_epoch` singleton** : CHECK + PRIMARY KEY constants. Évite la création accidentelle d'un 2e row.
- **`reverify_tokens.token_hash`** : on stocke le hash du reverify_token, pas le token lui-même. Évite les leaks par dump DB.
- **CHECK avec subquery** : Postgres ne supporte pas. La contrainte "linked_secret du même wallet" reste applicative.
- **`gen_random_uuid()`** vient de `pgcrypto`.
- **FK croisée secrets ↔ api_keys** : déclarée après création des deux tables via ALTER.
- **`BIGSERIAL` pour audit_log et identity_anomaly_events** : volume potentiellement élevé.

## Ce qui suit

Le **lot 02** ajoute l'authentification multi-identité, la détection d'anomalies, la quarantaine, et la re-vérification de passphrase.
