-- Migration 033 — Flux « Se connecter avec Harpocrate » (épic docflow
-- « Connecter une application à un wallet », plan du 2026-09-29).
--
-- Une application DÉCLARÉE (connect_clients) dépose une demande (PAR,
-- connect_requests) ; l'utilisateur consent, le navigateur crée l'API key et la
-- SCELLE pour une clé publique éphémère de l'application ; le backend de
-- l'application échange un code à usage unique contre le scellé.
--
-- Invariant de fond : le serveur ne voit jamais la clé de déchiffrement (dkey)
-- de la clé créée. Seul un JWE illisible pour lui (sealed_jwe) transite par
-- connect_requests, et il est effacé dès sa remise (contrainte ci-dessous).
--
-- Tables dédiées plutôt qu'une extension d'oauth_pending_session (décision
-- D12) : cette table-là est liée au flux Google Drive (FK vers
-- remote_backup_connection, provider limité à 'gdrive').

-- ─── Registre des applications autorisées ────────────────────────────────────

CREATE TABLE connect_clients (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Identifiant public, transmis dans les URLs : format restreint pour qu'il
    -- ne puisse jamais servir de vecteur d'injection (chemin, HTML, log).
    client_id           TEXT         NOT NULL UNIQUE
                                     CHECK (client_id ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
    -- Nom affiché à l'utilisateur au consentement : c'est CE nom qui fait foi,
    -- jamais une valeur fournie par la requête de l'application.
    name                TEXT         NOT NULL CHECK (char_length(name) BETWEEN 1 AND 128),
    description         TEXT         CHECK (description IS NULL OR char_length(description) <= 1000),
    -- Liste EXACTE des URLs de retour autorisées (comparaison stricte côté
    -- application) : protège contre la redirection ouverte (décision D1).
    redirect_uris       TEXT[]       NOT NULL
                                     CHECK (cardinality(redirect_uris) BETWEEN 1 AND 10),
    active              BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by_user_id  UUID         REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─── Demandes en cours ───────────────────────────────────────────────────────

CREATE TABLE connect_requests (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- SHA-256 de la référence opaque remise au navigateur (jamais stockée en clair).
    request_ref_hash       BYTEA        NOT NULL UNIQUE,
    client_pk              UUID         NOT NULL REFERENCES connect_clients(id) ON DELETE CASCADE,
    redirect_uri           TEXT         NOT NULL,
    state                  TEXT         NOT NULL CHECK (char_length(state) BETWEEN 1 AND 512),
    -- PKCE S256 uniquement : base64url sans padding d'un SHA-256 = 43 caractères.
    code_challenge         TEXT         NOT NULL CHECK (code_challenge ~ '^[A-Za-z0-9_-]{43}$'),
    requested_permissions  SMALLINT     NOT NULL CHECK (requested_permissions BETWEEN 1 AND 63),
    requested_ttl_days     INTEGER      CHECK (requested_ttl_days IS NULL
                                               OR requested_ttl_days BETWEEN 1 AND 3650),
    -- Clé PUBLIQUE éphémère de l'application (JWK EC P-256) ; la privée ne quitte
    -- jamais l'application.
    app_public_jwk         JSONB        NOT NULL,
    status                 TEXT         NOT NULL DEFAULT 'pending'
                                        CHECK (status IN ('pending', 'denied', 'sealed',
                                                          'delivered', 'expired')),
    user_id                UUID         REFERENCES users(id) ON DELETE CASCADE,
    wallet_id              UUID         REFERENCES wallets(id) ON DELETE CASCADE,
    api_key_id             UUID         REFERENCES api_keys(id) ON DELETE SET NULL,
    sealed_jwe             TEXT,
    -- SHA-256 du code à usage unique (jamais stocké en clair).
    code_hash              BYTEA        UNIQUE,
    code_expires_at        TIMESTAMPTZ,
    expires_at             TIMESTAMPTZ  NOT NULL,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Une demande scellée porte forcément son scellé et un code valide.
    CONSTRAINT connect_requests_sealed_complete CHECK (
        status <> 'sealed'
        OR (sealed_jwe IS NOT NULL AND code_hash IS NOT NULL AND code_expires_at IS NOT NULL)
    ),
    -- Invariant du cadrage : une fois remis, le scellé ne doit plus exister en base.
    CONSTRAINT connect_requests_delivered_erased CHECK (
        status <> 'delivered' OR sealed_jwe IS NULL
    )
);

CREATE INDEX idx_connect_requests_expires ON connect_requests(expires_at);
CREATE INDEX idx_connect_requests_client  ON connect_requests(client_pk);

-- ─── Rattachement d'une API key à l'application qui l'a demandée (D14) ───────
-- Nullable : les clés existantes (créées à la main) restent valides et inchangées.

ALTER TABLE api_keys
    ADD COLUMN connect_client_id UUID REFERENCES connect_clients(id) ON DELETE SET NULL;
