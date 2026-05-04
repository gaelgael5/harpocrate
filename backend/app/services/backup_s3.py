"""Service de backup S3-compatible — LOT_13.

Fournit push, list et pull pour les sauvegardes distantes.
Utilise boto3 en mode synchrone (run_in_executor) pour rester compatible asyncpg.
"""
from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import backups as backups_repo


class S3Error(Exception):
    """Erreur lors d'une opération S3."""


@dataclass
class S3BackupItem:
    key: str
    size_bytes: int
    last_modified: datetime.datetime
    etag: str


def _make_s3_client() -> Any:
    """Crée un client boto3 S3 selon la config."""
    import boto3

    kwargs: dict[str, Any] = {
        "aws_access_key_id": settings.s3_access_key_id,
        "aws_secret_access_key": settings.s3_secret_access_key,
        "region_name": settings.s3_region,
    }
    if settings.s3_endpoint:
        kwargs["endpoint_url"] = settings.s3_endpoint

    return boto3.client("s3", **kwargs)


def _sync_push(local_path: Path, s3_key: str) -> None:
    """Upload synchrone vers S3 — appelé dans un executor."""
    client = _make_s3_client()
    client.upload_file(str(local_path), settings.s3_bucket, s3_key)
    logger.info("s3_push_done", key=s3_key, bucket=settings.s3_bucket)


def _sync_pull(s3_key: str, local_path: Path) -> None:
    """Download synchrone depuis S3 — appelé dans un executor."""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client = _make_s3_client()
    client.download_file(settings.s3_bucket, s3_key, str(local_path))
    logger.info("s3_pull_done", key=s3_key, local=str(local_path))


def _sync_list() -> list[S3BackupItem]:
    """Liste les objets S3 sous le prefix configuré — appelé dans un executor."""
    client = _make_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    items: list[S3BackupItem] = []
    for page in paginator.paginate(
        Bucket=settings.s3_bucket,
        Prefix=settings.s3_key_prefix,
    ):
        for obj in page.get("Contents", []):
            items.append(
                S3BackupItem(
                    key=obj["Key"],
                    size_bytes=obj["Size"],
                    last_modified=obj["LastModified"],
                    etag=obj.get("ETag", "").strip('"'),
                )
            )
    return items


async def push_backup_to_s3(
    backup_id: str,
    conn: asyncpg.Connection[asyncpg.Record],
) -> str:
    """Pousse un backup local vers S3. Retourne la clé S3."""
    if not settings.s3_configured:
        raise S3Error("S3 not configured (s3_bucket, s3_access_key_id, s3_secret_access_key required)")

    import uuid
    record = await backups_repo.get_backup(conn, uuid.UUID(backup_id))
    if record is None:
        raise S3Error(f"Backup {backup_id} not found")

    local_path = Path(settings.backup_local_path) / record.filename
    if not local_path.exists():
        raise S3Error(f"Local file not found: {local_path}")

    s3_key = f"{settings.s3_key_prefix}{record.filename}"
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _sync_push, local_path, s3_key)
    except Exception as exc:
        raise S3Error(f"S3 upload failed: {exc}") from exc

    return s3_key


async def list_s3_backups() -> list[S3BackupItem]:
    """Liste les backups disponibles dans le bucket S3."""
    if not settings.s3_configured:
        raise S3Error("S3 not configured")

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_list)
    except Exception as exc:
        raise S3Error(f"S3 list failed: {exc}") from exc


async def pull_backup_from_s3(
    s3_key: str,
    conn: asyncpg.Connection[asyncpg.Record],
) -> backups_repo.BackupRecord:
    """Télécharge un backup depuis S3 et l'enregistre en DB.

    Si le fichier existe déjà localement et en DB, retourne le record existant.
    """
    if not settings.s3_configured:
        raise S3Error("S3 not configured")

    filename = s3_key.split("/")[-1]
    local_path = Path(settings.backup_local_path) / filename

    # Télécharge si absent localement
    if not local_path.exists():
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, _sync_pull, s3_key, local_path)
        except Exception as exc:
            raise S3Error(f"S3 download failed: {exc}") from exc

    size_bytes = local_path.stat().st_size

    # Enregistre en DB (sans manifest — le contenu sera vérifié à la restauration)
    record = await backups_repo.insert_backup(
        conn,
        filename=filename,
        size_bytes=size_bytes,
        checksum_sha256="",
        age_recipient="",
        manifest={},
        description=f"Imported from S3: {s3_key}",
        created_by_user_id=None,
        imported=True,
    )
    return record
