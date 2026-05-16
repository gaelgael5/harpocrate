-- LOT remote-backups-gdrive — état éphémère d'un flux OAuth en cours.
-- Stocke les paramètres OAuth (client_id, client_secret, scope, payload UI)
-- entre le clic "Autoriser avec Google" côté frontend et le retour du callback
-- Google. TTL strict 10 min, purgé par job cron.
-- Une fois la connexion finalisée, la ligne est supprimée immédiatement.

CREATE TABLE oauth_pending_session (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    state                TEXT         NOT NULL UNIQUE,
    provider             TEXT         NOT NULL CHECK (provider IN ('gdrive')),
    payload              JSONB        NOT NULL,
    result               JSONB,
    status               TEXT         NOT NULL DEFAULT 'pending'
                                      CHECK (status IN ('pending', 'authorized', 'failed')),
    target_connection_id UUID         REFERENCES remote_backup_connection(id) ON DELETE CASCADE,
    created_by_user_id   UUID         REFERENCES users(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMPTZ  NOT NULL
);

CREATE INDEX idx_oauth_pending_session_state   ON oauth_pending_session(state);
CREATE INDEX idx_oauth_pending_session_expires ON oauth_pending_session(expires_at);
