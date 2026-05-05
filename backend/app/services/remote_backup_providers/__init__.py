"""Providers de backup distant — abstraction + implémentations par protocole.

Chaque provider implémente l'interface `RemoteBackupProvider` (cf. base.py) :
  - `test_connection()` : valide les credentials + l'accès au remote_path
  - `upload_stream(remote_filename, source)` : streame un AsyncIterator[bytes] vers le distant

Implémentations actuelles :
  - `sftp.SftpProvider`  (via asyncssh)

Implémentations futures (LOTs ultérieurs) :
  - s3-compat (générique + presets R2/B2/Scaleway/OVH)
  - FTPS, Azure Blob, GCS...
"""

from __future__ import annotations

from typing import Any

from app.services.remote_backup_providers.base import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
)
from app.services.remote_backup_providers.sftp import SftpProvider


def get_provider(
    kind: str, config: dict[str, Any], credentials: dict[str, Any]
) -> RemoteBackupProvider:
    """Factory : retourne l'implémentation correspondant au `kind` de connexion."""
    if kind == "sftp":
        return SftpProvider(config=config, credentials=credentials)
    raise ValueError(f"Unsupported remote backup kind: {kind!r}")


__all__ = [
    "RemoteBackupProvider",
    "RemoteBackupProviderError",
    "SftpProvider",
    "get_provider",
]
