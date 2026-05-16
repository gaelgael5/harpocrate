-- 029_system_metadata_standby.sql
--
-- LOT replication-pairing-wizard — mode asservi (standby).
-- Initialise la clé replication.is_standby_of à JSON null. Cette clé est mise
-- à jour par streaming_replication.set_standby_of à la fin du wizard
-- d'appairage et lue par le frontend pour afficher le bandeau "mode asservi"
-- + désactiver les actions de gestion réplication.

INSERT INTO system_metadata (key, value)
VALUES ('replication.is_standby_of', 'null'::jsonb)
ON CONFLICT (key) DO NOTHING;
