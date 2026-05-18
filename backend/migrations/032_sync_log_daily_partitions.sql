-- Migration 032 — Partitionnement journalier de sync_log + helpers de purge
--
-- Contexte : la migration 013 crée `sync_log` partitionnée `BY RANGE (occurred_at)`
-- mais une UNIQUE partition `sync_log_default` (catch-all). Sans partitions
-- explicites, `HARPOCRATE_SYNC_LOG_RETENTION_DAYS` ne pouvait pas être
-- appliqué (impossible de DROP la default sans perdre toutes les données).
--
-- Cette migration ajoute deux fonctions PL/pgSQL utilisées par le scheduler
-- applicatif `app.services.sync_log_partition_scheduler` :
--   - `ensure_sync_log_partition(target_date)` : crée la partition pour
--     un jour donné (idempotent, sans bloquer si elle existe déjà).
--   - `drop_old_sync_log_partitions(retention_days)` : supprime les
--     partitions plus anciennes que `now() - retention_days` jours.
--
-- La partition `sync_log_default` reste en place comme filet de sécurité :
-- elle catch les inserts dont la date sortirait des partitions explicites
-- (ex: insert avec `occurred_at = '1970-01-01'`). Le scheduler ne la
-- touche JAMAIS — la conserver garantit qu'aucun insert ne plante.
--
-- Format des partitions journalières : `sync_log_YYYY_MM_DD` (UTC).
-- Le scheduler crée systématiquement les partitions pour `today` et
-- `today+1` à chaque tick horaire — les inserts du jour vont dans la
-- partition explicite, les inserts hors fenêtre vont dans `default`.

-- ─── ensure_sync_log_partition ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION ensure_sync_log_partition(target_date DATE)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_ts TEXT;
    end_ts TEXT;
BEGIN
    -- Nom déterministe en UTC : sync_log_YYYY_MM_DD
    partition_name := 'sync_log_' || to_char(target_date, 'YYYY_MM_DD');

    -- Bornes en UTC explicites pour ne pas dépendre du TIMEZONE de la session.
    start_ts := to_char(target_date, 'YYYY-MM-DD') || ' 00:00:00+00';
    end_ts := to_char(target_date + 1, 'YYYY-MM-DD') || ' 00:00:00+00';

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF sync_log
            FOR VALUES FROM (%L) TO (%L)',
        partition_name, start_ts, end_ts
    );

    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

-- ─── drop_old_sync_log_partitions ────────────────────────────────────────────
-- Drop les partitions journalières dont la date < CURRENT_DATE - retention_days.
-- Ne touche PAS à `sync_log_default` (la partition catch-all reste en place).
-- Retourne le nombre de partitions effectivement supprimées.

CREATE OR REPLACE FUNCTION drop_old_sync_log_partitions(retention_days INT)
RETURNS INT AS $$
DECLARE
    cutoff_date DATE;
    partition_rec RECORD;
    partition_date DATE;
    dropped_count INT := 0;
BEGIN
    IF retention_days < 1 THEN
        RAISE EXCEPTION 'retention_days must be >= 1, got %', retention_days;
    END IF;

    cutoff_date := CURRENT_DATE - retention_days;

    FOR partition_rec IN
        SELECT child.relname AS partition_name
        FROM pg_inherits
        JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
        JOIN pg_class child ON pg_inherits.inhrelid = child.oid
        WHERE parent.relname = 'sync_log'
          -- Ne matche QUE les partitions journalières (exclut sync_log_default)
          AND child.relname ~ '^sync_log_[0-9]{4}_[0-9]{2}_[0-9]{2}$'
    LOOP
        BEGIN
            partition_date := to_date(
                substring(partition_rec.partition_name FROM 'sync_log_(.+)$'),
                'YYYY_MM_DD'
            );
        EXCEPTION WHEN OTHERS THEN
            -- Date non parseable : on skip cette partition (paranoïa)
            CONTINUE;
        END;

        IF partition_date < cutoff_date THEN
            EXECUTE format('DROP TABLE IF EXISTS %I', partition_rec.partition_name);
            dropped_count := dropped_count + 1;
        END IF;
    END LOOP;

    RETURN dropped_count;
END;
$$ LANGUAGE plpgsql;
