-- 024_scheduled_backups.sql
--
-- Sauvegardes planifiées (cron-like).
--
-- Chaque ligne = un planning : une expression cron, une cible (NULL = local
-- uniquement, sinon FK vers une connexion remote configurée), une tolérance
-- de "miss" (combien de minutes de retard sont acceptables avant de skip un
-- déclenchement manqué — utile après un redémarrage du process).
--
-- ON DELETE SET NULL sur remote_id : si l'admin supprime une connexion qui
-- était cible d'un planning, le planning ne disparaît pas — il devient
-- "local-only" et un trigger marque `remote_id_disconnected_at` pour que
-- l'UI affiche un warning explicite "ta connexion a été supprimée, ce
-- planning ne push plus nulle part".

CREATE TABLE scheduled_backup (
  id                          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
  name                        TEXT         NOT NULL,
  cron_expression             TEXT         NOT NULL,
  remote_id                   UUID         NULL REFERENCES remote_backup_connection(id) ON DELETE SET NULL,
  miss_threshold_minutes      INTEGER      NOT NULL DEFAULT 5
                              CHECK (miss_threshold_minutes IN (5, 10, 20, 30, 60)),
  enabled                     BOOLEAN      NOT NULL DEFAULT TRUE,
  description                 TEXT         NULL,
  next_run_at                 TIMESTAMPTZ  NOT NULL,
  last_run_at                 TIMESTAMPTZ  NULL,
  last_run_status             TEXT         NULL CHECK (last_run_status IN ('ok', 'failed', 'skipped')),
  last_run_error              TEXT         NULL,
  -- Marqué par trigger quand `remote_id` passe de non-NULL à NULL (suite à
  -- ON DELETE SET NULL ou edit explicite). Effacé manuellement par le PATCH
  -- quand l'admin reconfigure un remote_id ou acquitte le warning.
  remote_id_disconnected_at   TIMESTAMPTZ  NULL,
  created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Index unique sur le nom pour éviter les confusions UI ("Daily 2h" deux fois).
CREATE UNIQUE INDEX uq_scheduled_backup_name ON scheduled_backup(LOWER(name));

-- Index "due" : sert au scan régulier du scheduler (toutes les 60s).
CREATE INDEX idx_scheduled_backup_due ON scheduled_backup(next_run_at) WHERE enabled;

-- Trigger updated_at — pattern réutilisé d'autres tables.
CREATE TRIGGER trg_scheduled_backup_updated_at
  BEFORE UPDATE ON scheduled_backup
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Trigger de détection "remote supprimé" :
--   - Si remote_id passe de non-NULL à NULL → on stamp remote_id_disconnected_at
--   - Si remote_id passe de NULL à non-NULL → on clear remote_id_disconnected_at
--     (l'admin a réassigné un remote, le warning n'a plus lieu d'être)
CREATE OR REPLACE FUNCTION track_scheduled_backup_remote_change() RETURNS TRIGGER AS $$
BEGIN
  IF OLD.remote_id IS NOT NULL AND NEW.remote_id IS NULL THEN
    NEW.remote_id_disconnected_at := NOW();
  ELSIF OLD.remote_id IS NULL AND NEW.remote_id IS NOT NULL THEN
    NEW.remote_id_disconnected_at := NULL;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_scheduled_backup_track_remote
  BEFORE UPDATE ON scheduled_backup
  FOR EACH ROW EXECUTE FUNCTION track_scheduled_backup_remote_change();
