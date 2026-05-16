-- Migration 030 — Élargit le CHECK sur remote_backup_connection.kind (LOT_61)
--
-- Ajoute 'gdrive' (Google Drive OAuth user-delegated) aux kinds reconnus
-- pour remote_backup_connection.
-- Cela permet de configurer des backups distants vers Google Drive.

ALTER TABLE remote_backup_connection
    DROP CONSTRAINT IF EXISTS remote_backup_connection_kind_check;

ALTER TABLE remote_backup_connection
    ADD CONSTRAINT remote_backup_connection_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps', 'gdrive'));
