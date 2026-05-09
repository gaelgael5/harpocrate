-- =============================================================================
-- 018 — Stocke le transactionId Novu sur recovery_sessions (LOT_57)
--
-- Quand Harpocrate déclenche le workflow Novu `recovery-session`, Novu
-- retourne un identifiant unique (transactionId) qui permet de retrouver
-- l'event côté Novu pour debug / monitoring / corrélation logs.
-- On le persiste à côté de la session pour traçabilité.
-- =============================================================================

ALTER TABLE recovery_sessions ADD COLUMN novu_transaction_id TEXT;

CREATE INDEX IF NOT EXISTS idx_recovery_sessions_novu_tx
    ON recovery_sessions(novu_transaction_id)
    WHERE novu_transaction_id IS NOT NULL;
