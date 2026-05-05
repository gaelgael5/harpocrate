-- Migration 011 — Séquence stricte sur audit_log (LOT_21A)
--
-- En cluster, les horloges des nœuds peuvent diverger malgré NTP : pour ordonner
-- strictement les évènements au-delà de la résolution seconde, on ajoute une
-- séquence Postgres globale `seq`. Toutes les requêtes audit ordonnent
-- désormais par `seq DESC` plutôt que `occurred_at DESC`.
--
-- (LOT 19, décision D-5 : NTP obligatoire mais seq comme filet de sécurité.)

ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS seq BIGSERIAL;

CREATE INDEX IF NOT EXISTS idx_audit_log_seq
    ON audit_log(seq DESC);
