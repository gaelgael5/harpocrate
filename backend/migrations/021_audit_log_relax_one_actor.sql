-- =============================================================================
-- 021 — Relâche la contrainte audit_log_one_actor (LOT_57)
--
-- La contrainte initiale exigeait EXACTEMENT un acteur entre `actor_user_id`
-- et `actor_api_key_id`. Elle empêche le `ON DELETE SET NULL` cascade sur
-- `audit_log.actor_user_id` quand on DELETE un user (cas LOT_57 — destruction
-- de compte via /auth/recovery/{id}/abandon-account).
--
-- Nouveau contrat : AU PLUS un acteur. La combinaison (NULL, NULL) signifie
-- "acteur disparu" (user supprimé). Garde l'audit historique vivant.
--
-- L'invariant "exactement un acteur à l'INSERT" reste garanti applicativement
-- par `audit_log_insert` côté Python — la DB n'est pas un substitut à la
-- validation applicative pour ce cas.
-- =============================================================================

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_one_actor;

ALTER TABLE audit_log ADD CONSTRAINT audit_log_at_most_one_actor CHECK (
    (actor_user_id IS NOT NULL)::int + (actor_api_key_id IS NOT NULL)::int <= 1
);
