-- 027_replication_observations_and_thresholds.sql
--
-- LOT réplication itération 2.
--
-- 1) Historique des observations par node : chaque tick du worker
--    (toutes les 30s) insère une row {node_id, observed_at, state, lag_bytes}.
--    Sert à afficher un graph d'évolution dans la page détaillée d'un node.
--
--    Rétention 7 jours : worker de purge horaire qui DELETE les rows
--    plus anciennes (volumétrie ~20k rows/node/7j, OK).
--
-- 2) Seed des seuils de lag par défaut dans system_metadata. L'admin peut
--    les modifier via l'UI (PATCH /streaming/lag-thresholds).
--    - warning : 64 MB
--    - critical : 512 MB

CREATE TABLE replication_node_observations (
    id              BIGSERIAL PRIMARY KEY,
    node_id         UUID NOT NULL REFERENCES replication_nodes(id) ON DELETE CASCADE,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- last_state au moment du tick (streaming/catchup/disconnected/unknown).
    -- NULL n'est pas autorisé car on ne crée d'observation que si le worker
    -- a effectivement vu le node (présent dans pg_stat_replication ou
    -- explicitement absent depuis qu'on l'avait vu).
    state           TEXT NOT NULL,
    -- pg_wal_lsn_diff(sent_lsn, replay_lsn). NULL si state='disconnected'
    -- ou 'unknown' (pas de mesure possible).
    lag_bytes       BIGINT,

    CONSTRAINT replication_node_obs_state_check
        CHECK (state IN ('streaming', 'catchup', 'disconnected', 'unknown'))
);

-- Index pour la query dominante : "donne-moi les observations d'un node
-- depuis tel timestamp, ordre chronologique".
CREATE INDEX idx_replication_node_obs_node_time
    ON replication_node_observations(node_id, observed_at DESC);

-- Index pour la purge.
CREATE INDEX idx_replication_node_obs_purge
    ON replication_node_observations(observed_at);

-- Seed des seuils dans system_metadata. ON CONFLICT pour idempotence.
INSERT INTO system_metadata (key, value)
VALUES (
    'replication_lag_thresholds',
    '{"warning_bytes": 67108864, "critical_bytes": 536870912}'::jsonb
)
ON CONFLICT (key) DO NOTHING;
