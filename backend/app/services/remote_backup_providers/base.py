"""Interface abstraite pour les providers de backup distant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class RemoteBackupProviderError(Exception):
    """Erreur générique remontée par un provider (connexion, auth, upload, etc.).

    L'exception encapsule le détail technique. Les routes admin la traduisent en
    HTTP 502/503 avec un message lisible côté UI.
    """


class RemoteBackupProvider(Protocol):
    """Contrat commun à tous les providers (SFTP, S3, FTPS...)."""

    async def test_connection(self) -> None:
        """Vérifie que la connexion peut être ouverte et que le remote_path est accessible.

        Lève RemoteBackupProviderError en cas d'échec (auth, host inaccessible, path
        inexistant, droits insuffisants, etc.).
        """
        ...

    async def upload_stream(
        self,
        remote_filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        """Streame `source` vers `remote_path/remote_filename` sur le serveur distant.

        Retourne le nombre total d'octets envoyés. Lève RemoteBackupProviderError en cas
        d'échec.

        Le streaming évite d'écrire le backup sur disque local côté Harpocrate.
        """
        ...
