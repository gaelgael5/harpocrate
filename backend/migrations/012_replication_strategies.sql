-- Migration 012 — Stratégies de réplication (LOT_20)
--
-- Une seule stratégie de réplication peut être active à la fois (contrainte
-- EXCLUDE). L'admin peut basculer entre stratégies depuis l'UI.

CREATE TABLE IF NOT EXISTS replication_strategies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type                TEXT NOT NULL,
    label               TEXT NOT NULL,
    description         TEXT,
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT replication_strategies_type_check
        CHECK (type IN ('none', 'patroni', 'harpocrate_sync', 's3_wal'))
);

-- Au plus une stratégie active à la fois (EXCLUDE filtré sur is_active = TRUE)
CREATE UNIQUE INDEX IF NOT EXISTS idx_replication_strategies_one_active
    ON replication_strategies ((TRUE)) WHERE is_active = TRUE;

CREATE TRIGGER trg_replication_strategies_updated_at
    BEFORE UPDATE ON replication_strategies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Seed : stratégie standalone par défaut, active.
-- Idempotent : ON CONFLICT DO NOTHING sur le label.
INSERT INTO replication_strategies (type, label, description, is_active)
VALUES (
    'none',
    'Standalone',
    'Postgres standalone — aucune réplication',
    TRUE
)
ON CONFLICT DO NOTHING;
