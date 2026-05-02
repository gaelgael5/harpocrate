-- =============================================================================
-- Harpocrate — Gouvernance d'identité (LOT_02 enrichi)
-- =============================================================================
-- Cette migration ajoute le socle multi-provider + détection d'anomalies +
-- quarantaine + reverify token + epoch de session serveur, sans casser le
-- schéma 001 actuel.
--
-- ⚠️  La colonne `users.keycloak_sub` existante est CONSERVÉE. Le code se
--     base encore dessus en attendant la bascule vers `user_external_identities`.
--     Une migration 003 viendra dropper la colonne quand le code sera migré.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- USERS — Colonnes de gouvernance d'identité
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS quarantine_until           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS quarantine_reason          TEXT,
    ADD COLUMN IF NOT EXISTS force_reverify_next_login  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS disabled_at                TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS disabled_reason            TEXT;

CREATE INDEX IF NOT EXISTS idx_users_quarantine ON users(quarantine_until)
    WHERE quarantine_until IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_disabled ON users(disabled_at)
    WHERE disabled_at IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- USER EXTERNAL IDENTITIES — multi-provider OIDC (Google, GitHub, etc.)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_external_identities (
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

CREATE INDEX IF NOT EXISTS idx_user_external_user
    ON user_external_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_external_lookup
    ON user_external_identities(provider, external_subject);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_external_one_primary
    ON user_external_identities(user_id) WHERE is_primary = TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- IDENTITY ANOMALY EVENTS — détection des changements suspects
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS identity_anomaly_events (
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

CREATE INDEX IF NOT EXISTS idx_identity_anomaly_user
    ON identity_anomaly_events(user_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_identity_anomaly_unack
    ON identity_anomaly_events(user_id) WHERE acknowledged_at IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- REVERIFY TOKENS — preuves de re-vérification de passphrase pour actions sensibles
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reverify_tokens (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash                      BYTEA NOT NULL,
    issued_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at                      TIMESTAMPTZ NOT NULL,
    consumed_at                     TIMESTAMPTZ,

    CONSTRAINT reverify_expires_after_issued CHECK (expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS idx_reverify_user_active
    ON reverify_tokens(user_id, expires_at) WHERE consumed_at IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- SERVER SESSION EPOCH — invalide tous les JWT après un restore de backup
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS server_session_epoch (
    id                              INTEGER PRIMARY KEY DEFAULT 1,
    epoch                           BIGINT NOT NULL DEFAULT 1,
    rotated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_reason                  TEXT,

    CONSTRAINT server_session_epoch_singleton CHECK (id = 1)
);

-- Initialisation idempotente (ON CONFLICT pour pouvoir re-jouer la migration)
INSERT INTO server_session_epoch (id, epoch, rotated_reason)
VALUES (1, 1, 'initial')
ON CONFLICT (id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- BACKFILL — migrer les keycloak_sub existants vers user_external_identities
-- ─────────────────────────────────────────────────────────────────────────────
-- Pour chaque user déjà bootstrappé, créer une ligne user_external_identities
-- avec provider='keycloak_internal' et is_primary=TRUE. Idempotent grâce au
-- ON CONFLICT (provider, external_subject) DO NOTHING.

INSERT INTO user_external_identities (
    user_id, provider, external_subject, is_primary,
    linked_at, linked_email, linked_display_name
)
SELECT
    u.id,
    'keycloak_internal' AS provider,
    u.keycloak_sub AS external_subject,
    TRUE AS is_primary,
    u.created_at AS linked_at,
    u.email AS linked_email,
    u.display_name AS linked_display_name
FROM users u
WHERE u.keycloak_sub IS NOT NULL
ON CONFLICT (provider, external_subject) DO NOTHING;
