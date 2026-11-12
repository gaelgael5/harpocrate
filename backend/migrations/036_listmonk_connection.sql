-- Migration 036 — Connexion Listmonk paramétrée en base
-- (épic docflow « Cultures et templates Listmonk paramétrés en base », feature 3).
--
-- L'admin doit pouvoir changer URL, utilisateur et token depuis l'IHM : le
-- backend ne peut ni écrire le .env de l'hôte (non monté) ni se recréer (il
-- faudrait le socket Docker, soit un accès root à l'hôte). La connexion est
-- donc lue ici ; HARPOCRATE_LISTMONK_URL/USER/TOKEN ne servent plus qu'à une
-- reprise unique au boot.

CREATE TABLE listmonk_connection (
    -- Ligne unique : une instance parle à un seul Listmonk.
    id                  BOOLEAN      PRIMARY KEY DEFAULT TRUE CHECK (id),
    url                 TEXT         NOT NULL CHECK (char_length(url) BETWEEN 1 AND 2048),
    api_user            TEXT         NOT NULL CHECK (char_length(api_user) BETWEEN 1 AND 256),
    -- Token chiffré AES-256-GCM (app/core/server_secret_box.py) : jamais en
    -- clair en base ni dans un backup.
    token_encrypted     BYTEA        NOT NULL,
    updated_by_user_id  UUID         REFERENCES users(id) ON DELETE SET NULL,
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
