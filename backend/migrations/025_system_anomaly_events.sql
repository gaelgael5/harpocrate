-- 025_system_anomaly_events.sql
--
-- Anomalies système (vs anomalies par-utilisateur dans identity_anomaly_events).
--
-- Cas d'usage initial : push d'un snapshot vers une connexion remote a échoué.
-- Plus généralement : tout incident qui touche l'instance Harpocrate elle-même
-- (rotation manquée, push remote KO, replication désynchronisée, etc.) sans
-- être imputable à un utilisateur particulier.
--
-- Différences avec identity_anomaly_events :
--   - pas de user_id (anomalie d'infrastructure, pas de comportement user)
--   - source / source_ref_id pour rattacher à l'objet concerné
--     (ex: source='snapshot_remote_push' + source_ref_id=remote_id)
--   - message lisible côté UI sans avoir à parser metadata

CREATE TABLE system_anomaly_events (
    id                              BIGSERIAL PRIMARY KEY,
    detected_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity                        TEXT NOT NULL,
    anomaly_type                    TEXT NOT NULL,
    -- Source : module ou fonctionnalité qui a levé l'anomalie. Permet de
    -- filtrer/grouper côté UI (ex: 'snapshot_remote_push').
    source                          TEXT NOT NULL,
    -- Référence libre vers l'objet concerné (UUID d'un snapshot, d'un remote,
    -- d'un schedule, …). NULL si l'anomalie ne concerne pas un objet précis.
    source_ref_id                   UUID NULL,
    -- Message lisible affichable directement côté UI (sans dérouler metadata).
    message                         TEXT NOT NULL,
    metadata                        JSONB,
    acknowledged_at                 TIMESTAMPTZ,
    acknowledged_by_user_id         UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT system_anomaly_severity_valid
        CHECK (severity IN ('info', 'warning', 'critical'))
);

-- Index pour le scan "non-acquittées récentes" (cas dominant côté UI).
CREATE INDEX idx_system_anomaly_unack
    ON system_anomaly_events(detected_at DESC)
    WHERE acknowledged_at IS NULL;

-- Index pour grouper par source (ex: voir tous les push remote ratés).
CREATE INDEX idx_system_anomaly_source
    ON system_anomaly_events(source, source_ref_id);
