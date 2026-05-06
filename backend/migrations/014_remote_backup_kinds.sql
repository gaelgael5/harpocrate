-- Migration 014 — Élargit le CHECK sur remote_backup_connection.kind (LOT_55)
--
-- Ajoute s3 (S3-compatible : AWS, Cloudflare R2, Backblaze B2, Scaleway, OVH)
-- et ftps (FTP/FTPS via aioftp) en plus de sftp existant.
-- Les nouveaux providers sont implémentés dans app/services/remote_backup_providers/.

ALTER TABLE remote_backup_connection
    DROP CONSTRAINT IF EXISTS remote_backup_connection_kind_check;

ALTER TABLE remote_backup_connection
    ADD CONSTRAINT remote_backup_connection_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps'));
