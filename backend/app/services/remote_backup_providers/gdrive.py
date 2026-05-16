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

import logging
from collections.abc import AsyncIterator
from typing import Any

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
        raise NotImplementedError  # implémenté en incrément 2

    async def upload_stream(
        self, path: str, remote_filename: str, source: AsyncIterator[bytes]
    ) -> int:
        raise NotImplementedError  # implémenté en incrément 3
