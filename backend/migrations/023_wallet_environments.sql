-- =============================================================================
-- 023 — Environnements de wallet (LOT_58)
--
-- Permet à chaque utilisateur de regrouper ses wallets par contexte
-- (ex: dev, staging, prod, perso, …). La liste est PAR-USER : chaque user
-- maintient ses propres environnements.
--
-- Convention : `environment_id IS NULL` côté wallet = environnement "None"
-- (item virtuel affiché par le frontend, pas de seed à maintenir).
--
-- ON DELETE RESTRICT sur wallets.environment_id : empêche de supprimer un
-- env qui contient encore des wallets (le service vérifie + remonte 409
-- au caller pour message UI explicite).
-- =============================================================================

CREATE TABLE wallet_environments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT wallet_environments_name_not_empty CHECK (length(trim(name)) > 0),
    UNIQUE (owner_user_id, name)
);

CREATE INDEX idx_wallet_environments_owner ON wallet_environments(owner_user_id);

ALTER TABLE wallets
    ADD COLUMN environment_id UUID REFERENCES wallet_environments(id) ON DELETE RESTRICT;

CREATE INDEX idx_wallets_environment ON wallets(environment_id) WHERE environment_id IS NOT NULL;
