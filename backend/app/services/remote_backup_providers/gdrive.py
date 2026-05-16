"""Provider Google Drive — OAuth user-delegated, scope drive.file.

Le `path` côté interface RemoteBackupProvider n'a pas de sémantique Drive
(Drive est plat avec des folder_id, pas des chemins POSIX). On le **ignore**
pour gdrive : l'arborescence est `<folder_name>/<remote_filename>` où
`folder_name` vient du config. Le `path` reste accepté pour conformité.

Format des dictionnaires attendus :

config = {
    "client_id":    "....apps.googleusercontent.com",
    "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
    "folder_name":  "Harpocrate Backups",
    "folder_id":    "1abc..." | None,   # rempli au premier test_connection si absent
    "user_email":   "admin@gmail.com" | None,
}
credentials = {
    "client_secret": "GOCSPX-...",
    "refresh_token": "1//0g...",
    "scope":         "https://www.googleapis.com/auth/drive.file",
    "token_uri":     "https://oauth2.googleapis.com/token",
}
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.services.remote_backup_providers import gdrive_client
from app.services.remote_backup_providers.base import RemoteBackupProviderError

_log = logging.getLogger(__name__)
_FOLDER_MIME = "application/vnd.google-apps.folder"
_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


class GoogleDriveProvider:
    """Provider Google Drive basé sur googleapiclient (sync) bridgé en async via threads."""

    def __init__(self, *, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self._client_id = str(config.get("client_id", "")).strip()
        if not self._client_id:
            raise ValueError("GDrive config: 'client_id' is required")
        self._folder_name = str(config.get("folder_name", "")).strip()
        if not self._folder_name:
            raise ValueError("GDrive config: 'folder_name' is required")
        self._folder_id = config.get("folder_id") or None

        self._client_secret = str(credentials.get("client_secret", "")).strip()
        if not self._client_secret:
            raise ValueError("GDrive credentials: 'client_secret' is required")
        self._refresh_token = str(credentials.get("refresh_token", "")).strip()
        if not self._refresh_token:
            raise ValueError("GDrive credentials: 'refresh_token' is required")
        self._token_uri = credentials.get("token_uri") or "https://oauth2.googleapis.com/token"
        self._scope = credentials.get("scope") or "https://www.googleapis.com/auth/drive.file"

    async def test_connection(self, path: str) -> dict[str, Any] | None:
        if path and path.strip() not in ("", "/", "."):
            _log.debug("gdrive provider ignores path argument", extra={"path": path})
        return await asyncio.to_thread(self._test_connection_sync)

    def _test_connection_sync(self) -> dict[str, Any] | None:
        creds = gdrive_client.build_credentials(
            client_id=self._client_id,
            client_secret=self._client_secret,
            refresh_token=self._refresh_token,
            token_uri=self._token_uri,
            scope=self._scope,
        )
        try:
            gdrive_client.refresh(creds)
        except Exception as exc:
            if exc.__class__.__name__ == "RefreshError":
                raise RemoteBackupProviderError(f"credentials_revoked: {exc}") from exc
            raise

        drive = gdrive_client.build_drive_service(creds)
        folder_id = self._folder_id
        patch_out: dict[str, Any] | None = None
        if not folder_id:
            folder_id = self._lookup_or_create_folder(drive)
            patch_out = {"folder_id": folder_id}

        # Liste le contenu pour valider l'accès.
        try:
            drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                pageSize=1,
                fields="files(id)",
            ).execute()
        except Exception as exc:
            raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
        return patch_out

    def _lookup_or_create_folder(self, drive: Any) -> str:
        """Cherche un dossier nommé self._folder_name en racine. Le crée si absent."""
        escaped = self._folder_name.replace("'", "\\'")
        try:
            result = (
                drive.files()
                .list(
                    q=f"name = '{escaped}' and mimeType = '{_FOLDER_MIME}' "
                    f"and 'root' in parents and trashed = false",
                    pageSize=1,
                    fields="files(id)",
                )
                .execute()
            )
        except Exception as exc:
            raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc

        items = result.get("files", [])
        if items:
            return str(items[0]["id"])

        try:
            created = (
                drive.files()
                .create(
                    body={
                        "name": self._folder_name,
                        "mimeType": _FOLDER_MIME,
                        "parents": ["root"],
                    },
                    fields="id",
                )
                .execute()
            )
        except Exception as exc:
            raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
        return str(created["id"])

    async def upload_stream(
        self, path: str, remote_filename: str, source: AsyncIterator[bytes]
    ) -> int:
        if "/" in remote_filename or "\\" in remote_filename:
            raise ValueError("remote_filename must not contain path separators")
        if not self._folder_id:
            raise RemoteBackupProviderError(
                "folder_id_missing: run test_connection first to discover/create the target folder"
            )

        # Buffer le AsyncIterator vers un fichier temp local (resumable upload sync
        # requiert un objet seekable). Le tmp est nettoyé en finally.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".gdrive-upload")  # noqa: SIM115
        tmp_path = Path(tmp.name)
        bytes_written = 0
        try:
            try:
                async for chunk in source:
                    tmp.write(chunk)
                    bytes_written += len(chunk)
            finally:
                tmp.close()
            await asyncio.to_thread(self._upload_sync, tmp_path, remote_filename)
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        return bytes_written

    def _upload_sync(self, tmp_path: Path, remote_filename: str) -> str:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        creds = gdrive_client.build_credentials(
            client_id=self._client_id,
            client_secret=self._client_secret,
            refresh_token=self._refresh_token,
            token_uri=self._token_uri,
            scope=self._scope,
        )
        try:
            gdrive_client.refresh(creds)
        except Exception as exc:
            if exc.__class__.__name__ == "RefreshError":
                raise RemoteBackupProviderError(f"credentials_revoked: {exc}") from exc
            raise

        drive = gdrive_client.build_drive_service(creds)
        media = MediaFileUpload(
            str(tmp_path),
            chunksize=_CHUNK_SIZE,
            resumable=True,
            mimetype="application/octet-stream",
        )
        try:
            created = (
                drive.files()
                .create(
                    body={"name": remote_filename, "parents": [self._folder_id]},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
        except HttpError as exc:
            content = (exc.content or b"").decode("utf-8", errors="replace")
            if "storageQuotaExceeded" in content:
                raise RemoteBackupProviderError(f"drive_storage_full: {content}") from exc
            if "userRateLimitExceeded" in content:
                raise RemoteBackupProviderError(f"drive_quota_exceeded: {content}") from exc
            raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
        except Exception as exc:
            raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
        return str(created["id"])
