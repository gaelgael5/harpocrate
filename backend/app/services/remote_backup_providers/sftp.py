"""Provider SFTP via asyncssh — streaming upload vers un serveur SSH/SFTP distant.

Le `path` est passé en argument à test_connection / upload_stream (pas dans config).
Une même connexion peut donc cibler plusieurs paths (snapshots, full).

Format des dictionnaires attendus :

config = {
    "host": "sftp.example.com",            # requis
    "port": 22,                            # défaut 22
    "host_key_fingerprint": "SHA256:...",  # optionnel — si présent, pinning de la host key
    # Les paths cible (remote_path_snapshots, remote_path_full) sont stockés
    # dans le config côté API mais ne sont PAS lus par le provider — ils sont
    # passés explicitement par le caller à chaque opération.
}

credentials = {
    "username": "harpo-backup",       # requis
    "auth_method": "password" | "private_key",
    "password": "...",                # si auth_method=password
    "private_key": "-----BEGIN ...",  # si auth_method=private_key
    "private_key_passphrase": "...",  # optionnel, si la clef est elle-même chiffrée
}
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import asyncssh

from app.services.remote_backup_providers.base import RemoteBackupProviderError


class SftpProvider:
    """Provider SFTP basé sur asyncssh."""

    def __init__(self, *, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self._host = str(config.get("host", "")).strip()
        if not self._host:
            raise ValueError("SFTP config: 'host' is required")

        port_raw = config.get("port", 22)
        try:
            self._port = int(port_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SFTP config: 'port' must be an integer (got {port_raw!r})") from exc

        self._host_key_fp = config.get("host_key_fingerprint") or None

        self._username = str(credentials.get("username", "")).strip()
        if not self._username:
            raise ValueError("SFTP credentials: 'username' is required")

        self._auth_method = str(credentials.get("auth_method", "password"))
        self._password = credentials.get("password") or None
        self._private_key = credentials.get("private_key") or None
        self._private_key_passphrase = credentials.get("private_key_passphrase") or None

        if self._auth_method == "password" and not self._password:
            raise ValueError("SFTP credentials: 'password' is required when auth_method='password'")
        if self._auth_method == "private_key" and not self._private_key:
            raise ValueError(
                "SFTP credentials: 'private_key' is required when auth_method='private_key'"
            )
        if self._auth_method not in ("password", "private_key"):
            raise ValueError(
                f"SFTP credentials: 'auth_method' must be 'password' or 'private_key' "
                f"(got {self._auth_method!r})"
            )

    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "username": self._username,
            "known_hosts": None,  # gestion via host_key_fingerprint si fourni
        }
        if self._auth_method == "password":
            kwargs["password"] = self._password
        else:
            client_keys = [
                asyncssh.import_private_key(
                    self._private_key, passphrase=self._private_key_passphrase
                )
            ]
            kwargs["client_keys"] = client_keys
        return kwargs

    async def _open_connection(self) -> asyncssh.SSHClientConnection:
        try:
            conn = await asyncssh.connect(**self._connect_kwargs())
        except (OSError, asyncssh.Error) as exc:
            raise RemoteBackupProviderError(f"SFTP connection failed: {exc}") from exc

        if self._host_key_fp:
            actual_fp = conn.get_server_host_key().get_fingerprint()
            if actual_fp != self._host_key_fp:
                conn.close()
                raise RemoteBackupProviderError(
                    f"SFTP host key fingerprint mismatch: expected {self._host_key_fp}, "
                    f"got {actual_fp}"
                )
        return conn

    async def test_connection(self, path: str) -> dict[str, Any] | None:
        """Ouvre une connexion SFTP, garantit l'existence de `path`, le liste, ferme.

        Si `path` n'existe pas, on tente de le créer (récursivement). Si la
        création échoue (permission denied, parent inaccessible, etc.), le
        message d'erreur inclut le `realpath('.')` du user pour révéler un
        éventuel chroot SFTP.
        """
        normalized = self._normalize_path(path)
        conn = await self._open_connection()
        try:
            async with conn.start_sftp_client() as sftp:
                await self._ensure_path(sftp, normalized)
                try:
                    await sftp.listdir(normalized)
                except (OSError, asyncssh.Error) as exc:
                    raise RemoteBackupProviderError(
                        f"SFTP cannot list path={normalized!r}: {exc}"
                    ) from exc
        finally:
            conn.close()
            await conn.wait_closed()
        return None

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalise un path utilisateur vers une forme exploitable côté SFTP."""
        cleaned = (path or "").strip()
        return cleaned or "."

    async def _ensure_path(self, sftp: Any, path: str) -> None:
        """Garantit que `path` existe et est un dossier accessible.

        Stratégie en deux étapes pour rester robuste face aux SFTP chrootés :
          1) `stat(path)` — si le dossier existe déjà, rien à faire
          2) sinon `makedirs(path, exist_ok=True)` — création récursive

        Si tout échoue, on enrichit le message avec `realpath('.')` (le home
        d'arrivée du user). Ça révèle immédiatement un chroot SFTP.
        """
        try:
            await sftp.stat(path)
            return
        except (OSError, asyncssh.Error):
            pass  # n'existe pas (ou inaccessible) — on tente de le créer

        try:
            await sftp.makedirs(path, exist_ok=True)
            return
        except (OSError, asyncssh.Error) as exc:
            cwd = "?"
            try:
                cwd_raw = await sftp.realpath(".")
                cwd = cwd_raw.decode() if isinstance(cwd_raw, bytes) else str(cwd_raw)
            except Exception:  # best-effort enrichment
                pass
            raise RemoteBackupProviderError(
                f"SFTP cannot prepare path={path!r}: {exc}. "
                f"User home (after login) is {cwd!r}. "
                f"Either create the directory on the server with write access "
                f"for this user, or set the path to a directory accessible "
                f"from {cwd!r} (chroot may restrict absolute paths)."
            ) from exc

    async def upload_stream(
        self,
        path: str,
        remote_filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        """Streame `source` vers `<path>/<remote_filename>` côté distant.

        Retourne le nombre total d'octets envoyés.
        """
        if "/" in remote_filename or "\\" in remote_filename:
            raise ValueError("remote_filename must not contain path separators")

        normalized = self._normalize_path(path)
        full_path = f"{normalized.rstrip('/')}/{remote_filename}"

        conn = await self._open_connection()
        bytes_written = 0
        try:
            async with conn.start_sftp_client() as sftp:
                # Garantit que le dossier de destination existe — sinon `open(..., "wb")`
                # échoue avec "No such file" car SFTP ne crée pas les parents implicitement.
                await self._ensure_path(sftp, normalized)
                try:
                    async with await sftp.open(full_path, "wb") as remote_file:
                        async for chunk in source:
                            await remote_file.write(chunk)
                            bytes_written += len(chunk)
                except (OSError, asyncssh.Error) as exc:
                    raise RemoteBackupProviderError(
                        f"SFTP upload to {full_path!r} failed: {exc}"
                    ) from exc
        finally:
            conn.close()
            await conn.wait_closed()
        return bytes_written
