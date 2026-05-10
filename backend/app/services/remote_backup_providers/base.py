"""Interface abstraite pour les providers de backup distant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class RemoteBackupProviderError(Exception):
    """Erreur générique remontée par un provider (connexion, auth, upload, etc.).

    L'exception encapsule le détail technique. Les routes admin la traduisent
    en HTTP 200 + ok:false (test) ou 422 (push) avec un message lisible côté UI.
    """


class RemoteBackupProvider(Protocol):
    """Contrat commun à tous les providers (SFTP, S3, FTPS...).

    Les providers sont **stateless sur le path** : `path` est passé en argument
    de chaque opération plutôt que stocké en attribut. Une même connexion
    (host + creds) peut donc cibler plusieurs paths (ex : un pour les
    snapshots, un pour les fulls) sans avoir à instancier deux providers.
    """

    async def test_connection(self, path: str) -> None:
        """Vérifie l'auth + l'accessibilité de `path` sur le serveur distant.

        Lève RemoteBackupProviderError en cas d'échec (auth, host inaccessible,
        path inexistant et non créable, droits insuffisants, etc.).
        """
        ...

    async def upload_stream(
        self,
        path: str,
        remote_filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        """Streame `source` vers `<path>/<remote_filename>` côté distant.

        Retourne le nombre total d'octets envoyés. Lève RemoteBackupProviderError
        en cas d'échec.

        Le streaming évite d'écrire le backup sur disque local côté Harpocrate
        (sauf S3 où boto3 impose un fichier temporaire pour le multipart sync).
        """
        ...
