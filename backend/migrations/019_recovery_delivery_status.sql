-- =============================================================================
-- 019 — Suivi de livraison des mails de recovery (LOT_57)
--
-- Stocke les états de livraison renvoyés par le service d'envoi de mail
-- (provider externe) via webhook. Architecture agnostique : les colonnes ne
-- mentionnent pas le provider, seul le `transaction_id` (déjà en place dans
-- `novu_transaction_id`) sert de clé de jointure.
--
-- Pattern :
--   1. Harpocrate déclenche un trigger → récupère un transaction_id
--   2. Le provider envoie le mail (asynchrone côté provider)
--   3. À chaque changement d'état, le provider POST /v1/webhooks/notify
--      avec event ∈ {message.sent, message.delivered, message.failed}
--   4. On UPDATE recovery_sessions WHERE novu_transaction_id = $1
--
-- Le `tracking_id` (UUID séparé du session_id) est destiné à un futur
-- endpoint WebSocket public qui pushera l'état au frontend en temps réel,
-- sans exposer le session_id (qui reste secret, reçu par mail uniquement).
-- =============================================================================

ALTER TABLE recovery_sessions
    ADD COLUMN tracking_id UUID UNIQUE DEFAULT gen_random_uuid();

-- Backfill pour les rows existantes (DEFAULT ne s'applique pas aux rows
-- pré-existantes lors d'un ADD COLUMN avec contrainte UNIQUE).
UPDATE recovery_sessions SET tracking_id = gen_random_uuid() WHERE tracking_id IS NULL;
ALTER TABLE recovery_sessions ALTER COLUMN tracking_id SET NOT NULL;

ALTER TABLE recovery_sessions
    ADD COLUMN sent_at TIMESTAMPTZ,
    ADD COLUMN delivery_status TEXT,
    ADD COLUMN delivery_status_at TIMESTAMPTZ;

ALTER TABLE recovery_sessions ADD CONSTRAINT recovery_sessions_delivery_status_valid CHECK (
    delivery_status IS NULL OR delivery_status IN ('sent', 'delivered', 'failed')
);

CREATE INDEX idx_recovery_sessions_tracking_id ON recovery_sessions(tracking_id);
