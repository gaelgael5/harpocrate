-- =============================================================================
-- 017 — Relâche la contrainte CHECK `attempts <= 3` sur recovery_sessions.
--
-- Le max d'attempts est désormais configurable côté application via
-- `HARPOCRATE_RECOVERY_MAX_ATTEMPTS` (default 3). La contrainte DB en dur
-- empêchait toute valeur > 3 — on la retire et on garde juste `attempts >= 0`.
-- =============================================================================

ALTER TABLE recovery_sessions DROP CONSTRAINT IF EXISTS recovery_sessions_attempts_range;

ALTER TABLE recovery_sessions ADD CONSTRAINT recovery_sessions_attempts_non_negative CHECK (
    attempts >= 0
);
