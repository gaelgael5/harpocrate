"""Endpoints /v1/admin/backups/* — LOT_12A / LOT_13 (S3) / LOT_L3 (push remote)."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.db.repositories import backups as backups_repo
from app.services import backup as backup_svc
from app.services import backup_s3 as backup_s3_svc
from app.services import remote_backup_connections as remote_svc
from app.services.audit import audit_log_insert
from app.services.remote_backup_providers import (
    RemoteBackupProviderError,
    get_provider,
)

# Taille des chunks pour le streaming vers SFTP. 64 KiB = bon compromis
# débit/mémoire ; chaque chunk est lu en thread pool pour ne pas bloquer le loop.
_PUSH_REMOTE_CHUNK_SIZE = 64 * 1024


async def _stream_file_chunks(path: Path) -> AsyncIterator[bytes]:
    """Yield le contenu de `path` par blocs de _PUSH_REMOTE_CHUNK_SIZE octets.

    Lit dans un thread pool pour ne pas bloquer la boucle asyncio.
    """
    f = await asyncio.to_thread(path.open, "rb")
    try:
        while True:
            chunk = await asyncio.to_thread(f.read, _PUSH_REMOTE_CHUNK_SIZE)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(f.close)

router = APIRouter(prefix="/admin/backups", tags=["admin-backups"])


def _backup_to_dict(r: backups_repo.BackupRecord) -> dict:
    return {
        "id": str(r.id),
        "filename": r.filename,
        "size_bytes": r.size_bytes,
        "checksum_sha256": r.checksum_sha256,
        "description": r.description,
        "created_at": r.created_at.isoformat(),
        "created_by_user_id": str(r.created_by_user_id) if r.created_by_user_id else None,
        "imported": r.imported,
        "manifest": r.manifest,
    }


@router.get("")
async def list_backups(
    admin: AdminJwt,
    limit: int = 50,
) -> JSONResponse:
    """Liste les backups locaux. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        records = await backups_repo.list_backups(conn, limit=limit)
    return JSONResponse({"backups": [_backup_to_dict(r) for r in records]})


class CreateBackupBody(BaseModel):
    description: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backup(body: CreateBackupBody, admin: AdminJwt) -> JSONResponse:
    """Crée un backup. Requiert rôle admin + age_public_key configuré."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            record = await backup_svc.create_backup(
                conn,
                description=body.description,
                created_by_user_id=None,
                created_by_email=admin.email,
            )
        except backup_svc.BackupError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "backup_failed", "message": str(e)},
            ) from e
        await audit_log_insert(
            conn, "admin.backup_created",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(record.id), "filename": record.filename},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=_backup_to_dict(record),
    )


# ─── S3 routes — must be before /{backup_id} to avoid UUID parse on "s3" ─────

@router.get("/s3")
async def list_s3_backups(admin: AdminJwt) -> JSONResponse:
    """Liste les backups disponibles dans le bucket S3."""
    try:
        items = await backup_s3_svc.list_s3_backups()
    except backup_s3_svc.S3Error as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "s3_list_failed", "message": str(e)},
        ) from e
    return JSONResponse({
        "backups": [
            {
                "key": item.key,
                "size_bytes": item.size_bytes,
                "last_modified": item.last_modified.isoformat(),
                "etag": item.etag,
            }
            for item in items
        ]
    })


class S3PullBody(BaseModel):
    s3_key: str


@router.post("/s3/pull", status_code=status.HTTP_201_CREATED)
async def pull_backup_from_s3(body: S3PullBody, admin: AdminJwt) -> JSONResponse:
    """Télécharge un backup depuis S3 et l'enregistre localement."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            record = await backup_s3_svc.pull_backup_from_s3(body.s3_key, conn)
        except backup_s3_svc.S3Error as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "s3_pull_failed", "message": str(e)},
            ) from e
        await audit_log_insert(
            conn, "admin.backup_pulled_s3",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(record.id), "s3_key": body.s3_key},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=_backup_to_dict(record),
    )


# ─── /{backup_id} routes ──────────────────────────────────────────────────────

@router.get("/{backup_id}")
async def get_backup(backup_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Retourne les détails d'un backup. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )
    return JSONResponse(_backup_to_dict(record))


@router.get("/{backup_id}/manifest")
async def get_backup_manifest(backup_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Retourne le manifest d'un backup (stocké en clair en DB). Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )
    return JSONResponse(record.manifest)


@router.get("/{backup_id}/download")
async def download_backup(backup_id: UUID, admin: AdminJwt) -> FileResponse:
    """Télécharge le fichier .tar.age. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )
        await audit_log_insert(
            conn, "admin.backup_downloaded",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "filename": record.filename},
        )

    path = Path(settings.backup_local_path) / record.filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "file_missing", "message": "Backup file not found on disk"},
        )
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=record.filename,
    )


class VerifyBody(BaseModel):
    age_private_key: str


@router.post("/{backup_id}/verify")
async def verify_backup(backup_id: UUID, body: VerifyBody, admin: AdminJwt) -> JSONResponse:
    """Vérifie l'intégrité du backup. La clé privée n'est jamais persistée."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await backup_svc.verify_backup(backup_id, body.age_private_key, conn)
        await audit_log_insert(
            conn, "admin.backup_verified",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "valid": result.valid},
        )
    return JSONResponse({
        "valid": result.valid,
        "manifest": result.manifest,
        "checksums_match": result.checksums_match,
        "dump_sql_lines": result.dump_sql_lines,
    })


@router.post("/{backup_id}/push-s3", status_code=status.HTTP_202_ACCEPTED)
async def push_backup_to_s3(backup_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Pousse un backup local vers S3. Requiert s3_configured."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            s3_key = await backup_s3_svc.push_backup_to_s3(str(backup_id), conn)
        except backup_s3_svc.S3Error as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "s3_push_failed", "message": str(e)},
            ) from e
        await audit_log_insert(
            conn, "admin.backup_pushed_s3",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "s3_key": s3_key},
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"s3_key": s3_key},
    )


@router.post(
    "/{backup_id}/push-to-remote/{remote_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def push_backup_to_remote(
    backup_id: UUID, remote_id: UUID, admin: AdminJwt
) -> JSONResponse:
    """Pousse un backup local vers une connexion remote (SFTP, etc.) en streaming.

    Le fichier n'est jamais chargé entièrement en mémoire : on lit par chunks de
    64 KiB et on streame vers le provider distant via `upload_stream`.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )
        remote = await remote_svc.get_connection(conn, remote_id)
        if remote is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "remote_not_found", "message": "Remote connection not found"},
            )
        creds = await remote_svc.get_decrypted_credentials(conn, remote_id)
        if creds is None:  # pragma: no cover — déjà filtré par get_connection
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "remote_not_found", "message": "Remote connection not found"},
            )

    file_path = Path(settings.backup_local_path) / record.filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "file_missing", "message": "Backup file not found on disk"},
        )

    provider = get_provider(remote.kind, remote.config, creds)
    try:
        bytes_sent = await provider.upload_stream(
            record.filename, _stream_file_chunks(file_path)
        )
    except RemoteBackupProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "remote_push_failed", "message": str(exc)},
        ) from exc

    async with pool.acquire() as conn:
        await audit_log_insert(
            conn,
            "admin.backup_pushed_remote",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={
                "backup_id": str(backup_id),
                "remote_id": str(remote_id),
                "remote_name": remote.name,
                "remote_filename": record.filename,
                "bytes_sent": bytes_sent,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "remote_id": str(remote_id),
            "remote_name": remote.name,
            "remote_filename": record.filename,
            "bytes_sent": bytes_sent,
        },
    )


@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_backup(backup_id: UUID, admin: AdminJwt) -> Response:
    """Supprime un backup. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )
        file_path = Path(settings.backup_local_path) / record.filename
        if file_path.exists():
            file_path.unlink()
        await backups_repo.delete_backup(conn, backup_id)
        await audit_log_insert(
            conn, "admin.backup_deleted",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "filename": record.filename},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RestoreBody(BaseModel):
    age_private_key: str
    confirmation: str
    auto_enable_maintenance: bool = True


@router.post("/{backup_id}/restore")
async def restore_backup(backup_id: UUID, body: RestoreBody, admin: AdminJwt) -> JSONResponse:
    """Restaure la base depuis un backup. DESTRUCTIF. Requiert confirmation textuelle exacte."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )

    stem = record.filename.removesuffix(".tar.age")
    expected = f"RESTORE {stem}"
    if body.confirmation != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "wrong_confirmation",
                "message": f"Confirmation must be exactly: '{expected}'",
            },
        )

    async with pool.acquire() as conn:
        try:
            result = await backup_svc.restore_backup(backup_id, body.age_private_key, conn)
        except backup_svc.BackupError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "restore_failed", "message": str(e)},
            ) from e
        await audit_log_insert(
            conn, "admin.restore_executed",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={
                "backup_id": str(backup_id),
                "session_epoch_new": result.session_epoch_new,
            },
        )

    return JSONResponse({
        "success": True,
        "restored_from_backup_id": str(result.restored_from_backup_id),
        "session_epoch_new": result.session_epoch_new,
        "env_restore_file_path": result.env_restore_file_path,
        "next_actions": [
            "Review the .env.restore file and merge into your .env if needed",
            "All active sessions are invalidated, users must re-login",
        ],
    })
