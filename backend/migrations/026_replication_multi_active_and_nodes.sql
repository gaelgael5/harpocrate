-- 026_replication_multi_active_and_nodes.sql
--
-- LOT réplication itération 1.
--
-- 1) On retire la contrainte "une seule stratégie active à la fois" :
--    plusieurs stratégies peuvent désormais coexister actives en parallèle
--    (ex: streaming_async ET s3_wal pour combiner réplication temps réel +
--    archive WAL pour PITR).
--
-- 2) On ajoute une stratégie "streaming_async" dans le seed (PostgreSQL
--    streaming replication async, hors-app — c'est l'admin qui configure
--    le standby via les snippets générés par l'UI).
--
-- 3) Nouvelle table `replication_nodes` : représente un standby
--    (potentiellement plusieurs) attaché à une stratégie. Pour streaming
--    c'est typiquement un serveur Postgres en mode hot standby.

-- ── 1) Multi-stratégies actives ─────────────────────────────────────────────

DROP INDEX IF EXISTS idx_replication_strategies_one_active;

-- ── 2) Seed streaming_async ─────────────────────────────────────────────────

-- Ajout du type 'streaming_async' au CHECK (drop+recreate la contrainte).
ALTER TABLE replication_strategies DROP CONSTRAINT IF EXISTS replication_strategies_type_check;
ALTER TABLE replication_strategies ADD CONSTRAINT replication_strategies_type_check
    CHECK (type IN ('none', 'patroni', 'harpocrate_sync', 's3_wal', 'streaming_async'));

INSERT INTO replication_strategies (type, label, description, is_active)
VALUES (
    'streaming_async',
    'Streaming async',
    'Réplication PostgreSQL streaming asynchrone — un ou plusieurs standby. Configuration des nodes hors-app (commandes générées par l''UI à exécuter en SSH).',
    FALSE
)
ON CONFLICT DO NOTHING;

-- ── 3) Table replication_nodes ──────────────────────────────────────────────

CREATE TABLE replication_nodes (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id                 UUID NOT NULL REFERENCES replication_strategies(id) ON DELETE CASCADE,

    label                       TEXT NOT NULL,                         -- "Standby LXC voisin"
    host                        TEXT NOT NULL,                         -- IP ou hostname du standby
    port                        INTEGER NOT NULL DEFAULT 5432,
    -- Nom du rôle Postgres créé sur le master pour ce standby.
    -- Unique pour permettre à plusieurs standbys d'exister sans collision.
    replication_user            TEXT NOT NULL,
    -- application_name : visible dans pg_stat_replication, sert à matcher la
    -- ligne du standby dans nos updates de last_state.
    application_name            TEXT NOT NULL,
    role                        TEXT NOT NULL DEFAULT 'standby_ro',
    notes                       TEXT,

    -- État observé via pg_stat_replication côté master, refresh périodique.
    last_seen_at                TIMESTAMPTZ,
    last_state                  TEXT,                                  -- streaming/catchup/disconnected/unknown
    last_lag_bytes              BIGINT,                                -- pg_wal_lsn_diff(sent_lsn, replay_lsn)

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id          UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT replication_nodes_role_check
        CHECK (role IN ('standby_ro', 'standby_failover_ready', 'archive_only')),
    CONSTRAINT replication_nodes_state_check
        CHECK (last_state IS NULL OR last_state IN ('streaming', 'catchup', 'disconnected', 'unknown'))
);

CREATE UNIQUE INDEX uq_replication_nodes_label
    ON replication_nodes(LOWER(label));

CREATE UNIQUE INDEX uq_replication_nodes_app_name
    ON replication_nodes(LOWER(application_name));

CREATE INDEX idx_replication_nodes_strategy
    ON replication_nodes(strategy_id);

CREATE TRIGGER trg_replication_nodes_updated_at
    BEFORE UPDATE ON replication_nodes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
