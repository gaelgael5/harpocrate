-- Migration 013 — Réplication applicative MQTT (LOT_21B)
--
-- Trois tables :
-- - sync_log         : journal des transactions + acks (partitionné par jour)
-- - sync_shelf       : étagère persistante des messages reçus hors-ordre
-- - sync_replication_state : état de réplication par peer
--
-- Triggers : INSERT dans sync_log à chaque modification des tables métier
--           (uniquement si sync_enabled=true en system_metadata).
--
-- E2E préservé (LOT 19, I-1) : les blobs encrypted_value sont répliqués
-- tels quels — aucune instance ne déchiffre pour répliquer.

-- ─── sync_log : journal partitionné par jour ─────────────────────────────────

CREATE TABLE IF NOT EXISTS sync_log (
    seq             BIGSERIAL,
    emitter_id      TEXT NOT NULL,
    type            TEXT NOT NULL,

    -- Pour type = 'transaction'
    entity_type     TEXT,
    entity_id       UUID,
    operation       TEXT CHECK (operation IS NULL OR operation IN ('upsert', 'delete')),
    payload         JSONB,
    is_replication  BOOLEAN NOT NULL DEFAULT FALSE,

    -- Pour type = 'replication_ack'
    source_emitter  TEXT,
    source_seq      BIGINT,

    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT sync_log_type_check
        CHECK (type IN ('transaction', 'replication_ack')),
    CONSTRAINT sync_log_transaction_check CHECK (
        type != 'transaction'
        OR (entity_type IS NOT NULL AND entity_id IS NOT NULL AND operation IS NOT NULL)
    ),
    CONSTRAINT sync_log_ack_check CHECK (
        type != 'replication_ack'
        OR (source_emitter IS NOT NULL AND source_seq IS NOT NULL)
    )
) PARTITION BY RANGE (occurred_at);

-- Partition par défaut (couvre toutes les dates pour le MVP).
-- Une cron applicative créera des partitions journalières dans un futur lot.
CREATE TABLE IF NOT EXISTS sync_log_default PARTITION OF sync_log DEFAULT;

CREATE INDEX IF NOT EXISTS idx_sync_log_emitter_seq
    ON sync_log(emitter_id, seq);
CREATE INDEX IF NOT EXISTS idx_sync_log_acks
    ON sync_log(source_emitter, source_seq)
    WHERE type = 'replication_ack';
CREATE INDEX IF NOT EXISTS idx_sync_log_occurred_at
    ON sync_log(occurred_at DESC);

-- Cursors et flags dans system_metadata (clé/valeur JSONB).
INSERT INTO system_metadata (key, value) VALUES
    ('sync_push_cursor', '0'::jsonb),
    ('sync_enabled', 'false'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- ─── sync_shelf : étagère pour messages hors-ordre ───────────────────────────

CREATE TABLE IF NOT EXISTS sync_shelf (
    source_emitter  TEXT NOT NULL,
    source_seq      BIGINT NOT NULL,
    payload         JSONB NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_emitter, source_seq)
);

CREATE INDEX IF NOT EXISTS idx_sync_shelf_received_at
    ON sync_shelf(received_at DESC);

-- ─── sync_replication_state : état par peer ──────────────────────────────────

CREATE TABLE IF NOT EXISTS sync_replication_state (
    peer_emitter        TEXT NOT NULL PRIMARY KEY,
    last_applied_seq    BIGINT NOT NULL DEFAULT 0,
    last_acked_seq      BIGINT NOT NULL DEFAULT 0,
    last_received_seq   BIGINT NOT NULL DEFAULT 0,
    last_seen_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('synced', 'lagging', 'unknown', 'stale'))
);

-- ─── Trigger générique sync_log ──────────────────────────────────────────────
--
-- Insère une ligne dans sync_log à chaque INSERT/UPDATE/DELETE sur les tables
-- métier. Ne s'active que si sync_enabled=true (cluster mode). En standalone,
-- les triggers existent mais ne font rien — coût négligeable.
--
-- L'emitter_id est lu depuis la session variable harpocrate.instance_id
-- (settée par l'app au démarrage). is_replication=true si la transaction
-- vient elle-même d'une réplication (évite les boucles infinies).

CREATE OR REPLACE FUNCTION sync_log_trigger()
RETURNS TRIGGER AS $$
DECLARE
    v_operation TEXT;
    v_payload JSONB;
    v_emitter TEXT;
    v_enabled BOOLEAN;
    v_entity_id UUID;
BEGIN
    SELECT (value::text = 'true'::text)
        INTO v_enabled
        FROM system_metadata WHERE key = 'sync_enabled';
    IF NOT COALESCE(v_enabled, FALSE) THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    BEGIN
        v_emitter := current_setting('harpocrate.instance_id');
    EXCEPTION WHEN OTHERS THEN
        v_emitter := 'unknown';
    END;

    IF TG_OP = 'DELETE' THEN
        v_operation := 'delete';
        v_entity_id := OLD.id;
        v_payload := jsonb_build_object('id', OLD.id);
    ELSE
        v_operation := 'upsert';
        v_entity_id := NEW.id;
        v_payload := to_jsonb(NEW);
    END IF;

    INSERT INTO sync_log (
        emitter_id, type, entity_type, entity_id,
        operation, payload, is_replication
    ) VALUES (
        v_emitter,
        'transaction',
        TG_TABLE_NAME,
        v_entity_id,
        v_operation,
        v_payload,
        COALESCE(current_setting('harpocrate.is_replication', true)::boolean, false)
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── Application sur les tables métier ──────────────────────────────────────
-- Note : on couvre les tables critiques. Audit_log n'est pas répliqué (chaque
-- nœud a son propre audit local) ni system_metadata (config locale).

DROP TRIGGER IF EXISTS trg_sync_secrets ON secrets;
CREATE TRIGGER trg_sync_secrets
    AFTER INSERT OR UPDATE OR DELETE ON secrets
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

DROP TRIGGER IF EXISTS trg_sync_wallets ON wallets;
CREATE TRIGGER trg_sync_wallets
    AFTER INSERT OR UPDATE OR DELETE ON wallets
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

DROP TRIGGER IF EXISTS trg_sync_users ON users;
CREATE TRIGGER trg_sync_users
    AFTER INSERT OR UPDATE OR DELETE ON users
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

DROP TRIGGER IF EXISTS trg_sync_wallet_grants ON wallet_grants;
CREATE TRIGGER trg_sync_wallet_grants
    AFTER INSERT OR UPDATE OR DELETE ON wallet_grants
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();
