"""Providers de backup distant — abstraction + implémentations par protocole.

Chaque provider implémente l'interface `RemoteBackupProvider` (cf. base.py) :
  - `test_connection()` : valide les credentials + l'accès au remote_path
  - `upload_stream(remote_filename, source)` : streame un AsyncIterator[bytes] vers le distant

Implémentations actuelles :
  - `sftp.SftpProvider`            (asyncssh)
  - `s3_compatible.S3CompatibleProvider`  (boto3 — AWS S3, Cloudflare R2,
                                           Backblaze B2, Scaleway, OVH)
  - `ftps.FtpsProvider`            (aioftp)
"""

from __future__ import annotations

from typing import Any

from app.services.remote_backup_providers.base import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
)
from app.services.remote_backup_providers.ftps import FtpsProvider
from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
from app.services.remote_backup_providers.sftp import SftpProvider

# Kinds reconnus côté API (admin_remote_backups.RemoteBackupCreate.kind).
SUPPORTED_KINDS: frozenset[str] = frozenset({"sftp", "s3", "ftps"})


def get_provider(
    kind: str, config: dict[str, Any], credentials: dict[str, Any]
) -> RemoteBackupProvider:
    """Factory : retourne l'implémentation correspondant au `kind` de connexion."""
    if kind == "sftp":
        return SftpProvider(config=config, credentials=credentials)
    if kind == "s3":
        return S3CompatibleProvider(config=config, credentials=credentials)
    if kind == "ftps":
        return FtpsProvider(config=config, credentials=credentials)
    raise ValueError(f"Unsupported remote backup kind: {kind!r}")


__all__ = [
    "SUPPORTED_KINDS",
    "FtpsProvider",
    "RemoteBackupProvider",
    "RemoteBackupProviderError",
    "S3CompatibleProvider",
    "SftpProvider",
    "get_provider",
]
