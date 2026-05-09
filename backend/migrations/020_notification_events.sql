-- =============================================================================
-- 020 — Table notification_events (LOT_57)
--
-- Remplace l'état "à plat" qu'on avait sur recovery_sessions (sent_at,
-- delivery_status, delivery_status_at) par un historique complet des events
-- reçus du provider d'envoi de mail.
--
-- Avantages :
--   - Historique complet : on garde la timeline (sent → delivery → open → click)
--     plutôt que de n'en conserver que le dernier état
--   - Extensible : nouveaux types d'events sans migration de schéma
--   - Générique : `transaction_id` est opaque, peut référencer n'importe quel
--     mail envoyé (recovery aujourd'hui, autres flows demain). Pas de FK
--     directe vers recovery_sessions pour garder cette généricité.
--
-- Convention d'ordre attendu pour un mail :
--   sent → delivery → open → click  (open et click optionnels selon tracking)
-- ou bien :
--   sent → failed                    (échec à un moment quelconque)
-- =============================================================================

CREATE TABLE notification_events (
    id              BIGSERIAL PRIMARY KEY,
    -- Identifiant opaque retourné par le provider au moment du trigger,
    -- même valeur que `recovery_sessions.novu_transaction_id` pour les
    -- mails de recovery. Pas une FK : on veut pouvoir tracer des mails
    -- d'autres flows sans toucher au schéma.
    transaction_id  TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    -- received_at = quand Harpocrate a reçu le webhook
    -- occurred_at = quand l'event s'est produit côté provider (peut différer
    --   en cas de retry / latence webhook)
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurred_at     TIMESTAMPTZ,
    -- Payload brut du webhook pour debug / replay (champs spécifiques au
    -- provider : IP du destinataire au open, URL cliquée, etc.).
    metadata        JSONB,

    CONSTRAINT notification_events_type_valid CHECK (
        event_type IN ('sent', 'delivery', 'open', 'click', 'failed')
    )
);

CREATE INDEX idx_notification_events_tx_received
    ON notification_events(transaction_id, received_at DESC);

CREATE INDEX idx_notification_events_type
    ON notification_events(event_type, received_at DESC);

-- Suppression des colonnes "à plat" de recovery_sessions devenues
-- redondantes — la source unique est désormais notification_events.
-- Le CHECK `recovery_sessions_delivery_status_valid` est automatiquement
-- supprimé avec la colonne `delivery_status`.
ALTER TABLE recovery_sessions DROP COLUMN IF EXISTS sent_at;
ALTER TABLE recovery_sessions DROP COLUMN IF EXISTS delivery_status;
ALTER TABLE recovery_sessions DROP COLUMN IF EXISTS delivery_status_at;
