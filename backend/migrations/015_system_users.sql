-- =============================================================================
-- 015 — Support des "system users" (admins sans matériel cryptographique).
--
-- Contexte : l'admin local (HARPOCRATE_ADMIN_LOCAL_*) et les admins Keycloak
-- pré-bootstrap ont besoin d'une row `users` pour pouvoir être référencés
-- comme `actor_user_id` dans `audit_log` (CHECK `audit_log_one_actor`).
-- Or ils n'ont pas de matériel crypto (RSA, KDF, …). On introduit un flag
-- `is_system` qui dispense ces users de remplir les colonnes crypto, tout en
-- préservant l'invariant pour les vrais users (is_system=FALSE).
-- =============================================================================

ALTER TABLE users ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT FALSE;

-- Relâche les NOT NULL des colonnes crypto + keycloak_sub (un local-admin n'a
-- pas de sub Keycloak). UNIQUE(keycloak_sub) reste valide : Postgres traite
-- les NULL comme distincts par défaut, donc plusieurs system users sans sub
-- sont autorisés (en pratique on n'en aura qu'un).
ALTER TABLE users ALTER COLUMN keycloak_sub                    DROP NOT NULL;
ALTER TABLE users ALTER COLUMN rsa_public_key                  DROP NOT NULL;
ALTER TABLE users ALTER COLUMN salt_passphrase                 DROP NOT NULL;
ALTER TABLE users ALTER COLUMN salt_recovery                   DROP NOT NULL;
ALTER TABLE users ALTER COLUMN encrypted_rsa_private_key       DROP NOT NULL;
ALTER TABLE users ALTER COLUMN encrypted_sym_key_by_pass       DROP NOT NULL;
ALTER TABLE users ALTER COLUMN encrypted_sym_key_by_recovery   DROP NOT NULL;
ALTER TABLE users ALTER COLUMN kdf_memory_kb                   DROP NOT NULL;
ALTER TABLE users ALTER COLUMN kdf_iterations                  DROP NOT NULL;
ALTER TABLE users ALTER COLUMN kdf_parallelism                 DROP NOT NULL;
ALTER TABLE users ALTER COLUMN rsa_key_size                    DROP NOT NULL;

-- Drop des CHECK actuels (deviennent caducs car les colonnes peuvent être NULL).
-- Ils sont absorbés par le CHECK groupé ci-dessous.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_kdf_memory_floor;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_kdf_iterations_floor;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_kdf_parallelism_floor;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_rsa_key_size_valid;

-- Un seul CHECK groupé : un vrai user (is_system=FALSE) doit avoir TOUT son
-- matériel crypto valide. Un system user en est dispensé.
ALTER TABLE users ADD CONSTRAINT users_real_user_has_crypto CHECK (
    is_system
    OR (
        keycloak_sub IS NOT NULL
        AND rsa_public_key IS NOT NULL
        AND salt_passphrase IS NOT NULL
        AND salt_recovery IS NOT NULL
        AND encrypted_rsa_private_key IS NOT NULL
        AND encrypted_sym_key_by_pass IS NOT NULL
        AND encrypted_sym_key_by_recovery IS NOT NULL
        AND kdf_memory_kb IS NOT NULL
        AND kdf_iterations IS NOT NULL
        AND kdf_parallelism IS NOT NULL
        AND rsa_key_size IS NOT NULL
        AND kdf_memory_kb >= 65536
        AND kdf_iterations >= 3
        AND kdf_parallelism >= 4
        AND rsa_key_size IN (2048, 4096)
    )
);

CREATE INDEX IF NOT EXISTS idx_users_is_system ON users(is_system) WHERE is_system = TRUE;
