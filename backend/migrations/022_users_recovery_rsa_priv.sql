-- =============================================================================
-- 022 — Permet la récupération zero-knowledge de rsa_priv via les 24 mots
--
-- Avant cette migration, le modèle crypto était :
--   encrypted_rsa_private_key      = AES(rsa_priv, pass_key)
--   encrypted_sym_key_by_pass      = AES(sym_key, pass_key)
--   encrypted_sym_key_by_recovery  = AES(sym_key, recovery_key)
--
-- Avec les 24 mots, on pouvait récupérer `sym_key` mais PAS `rsa_priv`
-- (chiffrée avec pass_key uniquement). Or `rsa_priv` est indispensable pour
-- déchiffrer les `wallet_grants.encrypted_wallet_key`. Le flow recovery
-- était donc inopérant.
--
-- On ajoute une copie de rsa_priv chiffrée avec recovery_key. Désormais :
--   encrypted_rsa_private_key_by_recovery = AES(rsa_priv, recovery_key)
--
-- L'utilisateur récupère sym_key + rsa_priv via ses 24 mots, choisit une
-- nouvelle passphrase, re-chiffre rsa_priv et sym_key avec la nouvelle
-- pass_key. La copie by_recovery reste inchangée (recovery_key constante).
--
-- Au renew_recovery (régénération des 24 mots), on re-chiffre cette copie
-- avec la NOUVELLE recovery_key.
--
-- Compatibilité : la colonne est NULLABLE. Les users créés avant cette
-- migration auront NULL → le flow recovery les détecte et affiche un
-- message clair ("recovery indisponible, faites renew_recovery").
-- =============================================================================

ALTER TABLE users
    ADD COLUMN encrypted_rsa_private_key_by_recovery BYTEA;

COMMENT ON COLUMN users.encrypted_rsa_private_key_by_recovery IS
    'rsa_priv chiffrée avec recovery_key (Argon2(seed_24mots, salt_recovery)). '
    'Permet la récupération zero-knowledge de rsa_priv via les 24 mots sans '
    'la passphrase. NULL pour les users créés avant LOT_57 fix recovery — '
    'recovery indisponible jusqu''à un prochain renew_recovery.';
