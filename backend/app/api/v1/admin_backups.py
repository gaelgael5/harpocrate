"""Endpoints /v1/admin/backups/* — LOT_12A."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.db.repositories import backups as backups_repo
from app.services import backup as backup_svc
from app.services.audit import audit_log_insert

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
            actor_user_id=None,
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
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(record.id), "filename": record.filename},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=_backup_to_dict(record),
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
            actor_user_id=None,
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


@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(backup_id: UUID, admin: AdminJwt) -> None:
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
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "filename": record.filename},
        )


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
            actor_user_id=None,
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
