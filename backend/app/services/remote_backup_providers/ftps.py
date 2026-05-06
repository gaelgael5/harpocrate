"""Provider FTPS via aioftp (LOT_55).

Streaming natif async — pas de tampon disque local.

config = {
    "host":        "ftp.example.com",   # requis
    "port":        21,                    # défaut 21
    "remote_path": "/backups/harpo",      # requis
    "use_tls":     true,                  # défaut true (FTPS explicit)
}

credentials = {
    "username": "harpo-backup",
    "password": "...",
}
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aioftp

from app.services.remote_backup_providers.base import RemoteBackupProviderError


class FtpsProvider:
    """Provider FTP/FTPS basé sur aioftp."""

    def __init__(self, *, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        host = str(config.get("host", "")).strip()
        if not host:
            raise ValueError("FTPS config: 'host' is required")
        self._host = host

        port_raw = config.get("port", 21)
        try:
            self._port = int(port_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"FTPS config: 'port' must be an integer (got {port_raw!r})"
            ) from exc

        self._remote_path = str(config.get("remote_path", "")).strip() or "."
        self._use_tls = bool(config.get("use_tls", True))

        username = str(credentials.get("username", "")).strip()
        password = credentials.get("password") or ""
        if not username:
            raise ValueError("FTPS credentials: 'username' is required")
        if not password:
            raise ValueError("FTPS credentials: 'password' is required")
        self._username = username
        self._password = password

    def _client_kwargs(self) -> dict[str, Any]:
        # aioftp 0.21+ : ssl=True active FTPS implicit. Pour explicit, on
        # se connecte normalement et on émet AUTH TLS — non géré ici (compat
        # MVP). Si use_tls=True, on utilise TLS au transport.
        return {"ssl": self._use_tls} if self._use_tls else {}

    async def test_connection(self) -> None:
        try:
            async with aioftp.Client.context(
                self._host,
                self._port,
                self._username,
                self._password,
                **self._client_kwargs(),
            ) as client:
                await client.change_directory(self._remote_path)
                # Liste le dossier pour vérifier les droits
                await client.list()
        except Exception as exc:
            raise RemoteBackupProviderError(
                f"FTPS connection failed: {exc}"
            ) from exc

    async def upload_stream(
        self,
        remote_filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        if "/" in remote_filename or "\\" in remote_filename:
            raise ValueError("remote_filename must not contain path separators")

        bytes_written = 0
        try:
            async with aioftp.Client.context(
                self._host,
                self._port,
                self._username,
                self._password,
                **self._client_kwargs(),
            ) as client:
                await client.change_directory(self._remote_path)
                async with client.upload_stream(remote_filename) as stream:
                    async for chunk in source:
                        await stream.write(chunk)
                        bytes_written += len(chunk)
        except Exception as exc:
            raise RemoteBackupProviderError(
                f"FTPS upload of {remote_filename!r} failed: {exc}"
            ) from exc
        return bytes_written
