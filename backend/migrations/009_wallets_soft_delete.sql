-- Migration 009 : suppression logique des wallets
-- deleted_at IS NULL  = wallet actif
-- deleted_at NOT NULL = suppression logique, purge physique 24h après

ALTER TABLE wallets ADD COLUMN deleted_at TIMESTAMPTZ;

-- Index pour la tâche de purge (ne parcourt que les lignes supprimées)
CREATE INDEX idx_wallets_deleted_at ON wallets(deleted_at) WHERE deleted_at IS NOT NULL;
