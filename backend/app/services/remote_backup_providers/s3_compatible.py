"""Provider S3-compatible (LOT_55).

Couvre AWS S3, Cloudflare R2, Backblaze B2, Scaleway Object Storage, OVH Object
Storage et tout service exposant l'API S3. La distinction se fait via
`config.endpoint_url` + `config.region` + éventuellement `config.path_style`.

Le `prefix` (clef de path) est passé en argument à test_connection / upload_stream
(pas dans config). Une même connexion peut donc cibler plusieurs prefixes
(snapshots, full).

Format des dictionnaires attendus :

config = {
    "endpoint_url": "https://s3.fr-par.scw.cloud",  # vide pour AWS S3
    "region":       "fr-par",                        # requis
    "bucket":       "harpocrate-backups",            # requis
    "path_style":   true,                             # true pour R2/B2/MinIO
    "object_lock":  true,                             # info uniquement
    # Les prefixes cible (prefix_snapshots, prefix_full) sont stockés dans
    # le config côté API mais ne sont PAS lus par le provider.
}

credentials = {
    "access_key_id":     "AKIA...",
    "secret_access_key": "...",
}

Limites connues :
- L'upload utilise un fichier temporaire local (boto3 multipart auto) pour
  bridger le AsyncIterator → fileobj sync. Coût disque == taille du backup,
  libéré à la fin. Pour les très gros backups (>10 GB), surveiller l'espace
  disque local.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.services.remote_backup_providers.base import RemoteBackupProviderError


class S3CompatibleProvider:
    """Provider S3-compatible basé sur boto3 (sync) bridgé en async via threads."""

    def __init__(self, *, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        bucket = str(config.get("bucket", "")).strip()
        if not bucket:
            raise ValueError("S3 config: 'bucket' is required")
        self._bucket = bucket

        region = str(config.get("region", "")).strip()
        if not region:
            raise ValueError("S3 config: 'region' is required")
        self._region = region

        self._endpoint_url = config.get("endpoint_url") or None
        self._path_style = bool(config.get("path_style", False))

        access = str(credentials.get("access_key_id", "")).strip()
        secret = credentials.get("secret_access_key") or ""
        if not access:
            raise ValueError("S3 credentials: 'access_key_id' is required")
        if not secret:
            raise ValueError("S3 credentials: 'secret_access_key' is required")
        self._access_key_id = access
        self._secret_access_key = secret

    def _make_client(self) -> Any:
        # Import paresseux : boto3 est lourd à importer (charge tous les services).
        import boto3
        from botocore.config import Config

        boto_config = Config(
            region_name=self._region,
            signature_version="s3v4",
            s3={"addressing_style": "path" if self._path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": self._region,
            "aws_access_key_id": self._access_key_id,
            "aws_secret_access_key": self._secret_access_key,
            "config": boto_config,
        }
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return boto3.client(**kwargs)

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        """`/foo/bar/` → `foo/bar/`, `''` reste `''`. Garantit le `/` final si non vide."""
        cleaned = (prefix or "").strip().lstrip("/")
        if cleaned and not cleaned.endswith("/"):
            cleaned += "/"
        return cleaned

    def _key_for(self, prefix: str, filename: str) -> str:
        normalized = self._normalize_prefix(prefix)
        return f"{normalized}{filename}" if normalized else filename

    async def test_connection(self, path: str) -> dict[str, Any] | None:
        """head_bucket → vérifie auth + accès au bucket. Le `path` (prefix) est
        validé par construction : les prefixes S3 n'ont pas besoin d'exister
        avant écriture (ils sont implicites). On valide juste le bucket.
        """
        # On normalise pour cohérence/log, mais aucun appel S3 sur le prefix.
        _ = self._normalize_prefix(path)

        def _check() -> None:
            try:
                client = self._make_client()
                client.head_bucket(Bucket=self._bucket)
            except Exception as exc:
                raise RemoteBackupProviderError(
                    f"S3 connection to bucket={self._bucket!r} failed: {exc}"
                ) from exc

        await asyncio.to_thread(_check)
        return None

    async def upload_stream(
        self,
        path: str,
        remote_filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        if "/" in remote_filename or "\\" in remote_filename:
            raise ValueError("remote_filename must not contain path separators")

        # On bufferise sur disque local : boto3 fera ensuite un multipart upload
        # automatique pour les gros fichiers. C'est le compromis le plus propre
        # entre asyncio (notre stream) et boto3 (sync, attend un fileobj sync).
        bytes_written = 0
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                async for chunk in source:
                    tmp.write(chunk)
                    bytes_written += len(chunk)
                tmp.flush()

                key = self._key_for(path, remote_filename)

                def _upload() -> None:
                    try:
                        client = self._make_client()
                        with tmp_path.open("rb") as f:
                            client.upload_fileobj(f, self._bucket, key)
                    except Exception as exc:
                        raise RemoteBackupProviderError(
                            f"S3 upload to s3://{self._bucket}/{key} failed: {exc}"
                        ) from exc

                await asyncio.to_thread(_upload)
            finally:
                # Suppression best-effort du tmp même si upload échoue
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
        return bytes_written
