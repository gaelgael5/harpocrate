-- 028_pairing_sessions.sql
--
-- LOT replication-pairing-wizard — appairage guidé entre 2 instances.
-- Stocke l'état d'une session d'appairage master/standby :
-- rôle local, code 4 chiffres échangé, URL du partenaire, statut
-- de progression, payload JSONB (creds réplication), curseur d'étape
-- pour le wizard, TTL strict.

CREATE TABLE pairing_session (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role          TEXT NOT NULL CHECK (role IN ('master', 'standby')),
    code          TEXT NOT NULL,
    partner_url   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','confirmed','wizard','completed','expired','failed')),
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_step_idx INTEGER NOT NULL DEFAULT 0,
    attempts      INTEGER NOT NULL DEFAULT 0,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX pairing_session_status_idx ON pairing_session(status);
CREATE INDEX pairing_session_code_pending_idx
    ON pairing_session(code) WHERE status IN ('pending', 'confirmed');
