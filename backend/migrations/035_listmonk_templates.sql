-- Migration 035 — Templates Listmonk par type de mail et par culture
-- (épic docflow « Cultures et templates Listmonk paramétrés en base », feature 2).
--
-- Remplace les variables HARPOCRATE_LISTMONK_TEMPLATE_RECOVERY_* du .env : les
-- ID de templates sont attribués par Listmonk (jamais choisis) et changent à
-- chaque nouveau serveur ; les poser depuis l'UI évite d'éditer le .env de
-- l'hôte et de recréer le conteneur. L'URL et les credentials Listmonk, eux,
-- restent dans le .env (secrets d'amorçage).

CREATE TABLE listmonk_templates (
    -- Type de mail. CHECK plutôt qu'une table de référence : un nouveau type
    -- demande du code (payload, déclencheur) ; la migration de contrainte qui
    -- l'accompagne est le moindre des changements.
    purpose             TEXT         NOT NULL CHECK (purpose IN ('recovery')),
    culture_code        TEXT         NOT NULL REFERENCES cultures(code),
    -- ID du template transactional côté Listmonk.
    template_id         INTEGER      NOT NULL CHECK (template_id > 0),
    updated_by_user_id  UUID         REFERENCES users(id) ON DELETE SET NULL,
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (purpose, culture_code)
);
