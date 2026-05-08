-- =============================================================================
-- 016 — Sessions de réinitialisation de passphrase via recovery seed (LOT_57)
--
-- Workflow :
--   1. Utilisateur clique "j'ai oublié ma passphrase" → POST /auth/recovery/start
--      avec son email. Une row pending est créée, un mail Novu est envoyé.
--   2. Lien email → GET /auth/recovery/{id} retourne les blobs crypto
--      nécessaires au déchiffrement client (salt_recovery, encrypted_sym_key
--      _by_recovery, etc.).
--   3. Client tente de dériver la sym_key avec les 24 mots BIP-39. Si KO →
--      POST /attempt-failed (incrémente le compteur, max 3).
--   4. Si OK : client re-chiffre rsa_private_key + sym_key avec la nouvelle
--      passphrase, POST /complete → les blobs `users` sont mis à jour et
--      la session passe à 'consumed'.
--   5. Sessions expirées (`expires_at < NOW()`) sont scannées par le worker
--      lifespan et passent à 'expired'. 5 sessions échouées/expirées sur
--      24h pour le même email → INSERT dans identity_anomaly_events.
-- =============================================================================

CREATE TABLE recovery_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- user_id NULL : on stocke quand même les sessions sur emails inconnus
    -- pour anti-énumération (le caller ne sait pas si l'email existe). Pour
    -- ces sessions, aucune action utile n'est possible côté serveur — elles
    -- expirent simplement à T+30min.
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INT NOT NULL DEFAULT 0,
    ip_started      INET,
    ip_consumed     INET,
    consumed_at     TIMESTAMPTZ,

    CONSTRAINT recovery_sessions_status_valid CHECK (
        status IN ('pending', 'consumed', 'failed', 'expired')
    ),
    CONSTRAINT recovery_sessions_attempts_range CHECK (
        attempts >= 0 AND attempts <= 3
    ),
    CONSTRAINT recovery_sessions_consumed_consistency CHECK (
        (status = 'consumed') = (consumed_at IS NOT NULL)
    )
);

-- Index pour le compteur anti-anomalie (count par email sur 24h).
CREATE INDEX idx_recovery_sessions_email_created
    ON recovery_sessions(email, created_at DESC);

-- Index pour le worker d'expiration (partial pour minimiser la taille).
CREATE INDEX idx_recovery_sessions_expires_pending
    ON recovery_sessions(expires_at)
    WHERE status = 'pending';
