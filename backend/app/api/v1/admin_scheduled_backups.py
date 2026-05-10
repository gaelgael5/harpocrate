"""Endpoints admin /v1/admin/scheduled-backups — sauvegardes planifiées (cron-like).

Auth : AdminJwt uniquement (rôle Keycloak `harpocrate-admin`).

Comportement clé :
  - `POST /test-cron` ne touche pas à la DB — sert au preview live UI.
  - `POST /{id}/run-now` partage le même `asyncio.Lock` que la boucle scheduler,
    donc on n'aura jamais de doublon (run manuel + tick au même moment).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.services import scheduled_backups as svc
from app.services import scheduled_backups_scheduler as scheduler_svc


router = APIRouter(prefix="/admin/scheduled-backups", tags=["admin-scheduled-backups"])


# ─── Models ──────────────────────────────────────────────────────────────────


class ScheduledBackupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    cron_expression: str = Field(min_length=1, max_length=128)
    remote_id: UUID | None = None
    miss_threshold_minutes: int = 5
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool = True


class ScheduledBackupPatch(BaseModel):
    """Update partiel. Pour distinguer `remote_id=None` (effacer) vs absent
    (ne pas toucher), utiliser `set_remote_id=true` avec `remote_id=null`.
    Idem `description`."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    remote_id: UUID | None = None
    set_remote_id: bool = False
    miss_threshold_minutes: int | None = None
    description: str | None = Field(default=None, max_length=2000)
    set_description: bool = False
    enabled: bool | None = None


class ValidateCronRequest(BaseModel):
    cron_expression: str = Field(min_length=1, max_length=128)


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_class=JSONResponse)
async def list_scheduled_backups(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        items = await svc.list_schedules(conn)
    return JSONResponse({"schedules": [s.to_dict() for s in items]})


@router.post("", status_code=status.HTTP_201_CREATED, response_class=JSONResponse)
async def create_scheduled_backup(
    body: ScheduledBackupCreate, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_id = await svc.create_schedule(
                conn,
                name=body.name,
                cron_expression=body.cron_expression,
                remote_id=body.remote_id,
                miss_threshold_minutes=body.miss_threshold_minutes,
                description=body.description,
                enabled=body.enabled,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_payload", "message": str(exc)},
            ) from exc
        except Exception as exc:
            msg = str(exc)
            if "unique" in msg.lower() or "23505" in msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "name_already_exists"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": msg},
            ) from exc
    return JSONResponse({"id": str(new_id)}, status_code=status.HTTP_201_CREATED)


@router.get("/{schedule_id}", response_class=JSONResponse)
async def get_scheduled_backup(schedule_id: UUID, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_schedule(conn, schedule_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "schedule_not_found"},
        )
    return JSONResponse(item.to_dict())


@router.patch("/{schedule_id}", response_class=JSONResponse)
async def update_scheduled_backup(
    schedule_id: UUID, body: ScheduledBackupPatch, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await svc.get_schedule(conn, schedule_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "schedule_not_found"},
            )
        try:
            affected = await svc.update_schedule(
                conn,
                schedule_id=schedule_id,
                name=body.name,
                cron_expression=body.cron_expression,
                remote_id=body.remote_id,
                set_remote_id=body.set_remote_id,
                miss_threshold_minutes=body.miss_threshold_minutes,
                description=body.description,
                set_description=body.set_description,
                enabled=body.enabled,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_payload", "message": str(exc)},
            ) from exc
    return JSONResponse({"updated": affected})


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_scheduled_backup(
    schedule_id: UUID, admin: AdminJwt
) -> Response:
    pool = await get_pool()
    async with pool.acquire() as conn:
        affected = await svc.delete_schedule(conn, schedule_id)
    if affected == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "schedule_not_found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{schedule_id}/run-now", response_class=JSONResponse)
async def run_scheduled_backup_now(
    schedule_id: UUID, admin: AdminJwt
) -> JSONResponse:
    """Déclenche immédiatement un schedule (acquiert le même lock que le
    scheduler — attend si un autre run est en cours).

    Ne décale pas `next_run_at` : un run manuel est en plus, pas en remplacement.
    """
    scheduler = scheduler_svc.get_scheduler()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "scheduler_not_started"},
        )
    result = await scheduler.run_now(schedule_id)
    payload: dict[str, Any] = {
        "status": result.status,
        "error": result.error,
        "backup_id": str(result.backup_id) if result.backup_id else None,
        "bytes_pushed": result.bytes_pushed,
    }
    return JSONResponse(payload)


@router.post("/validate-cron", response_class=JSONResponse)
async def validate_cron_expression(
    body: ValidateCronRequest, admin: AdminJwt
) -> JSONResponse:
    """Valide une expression cron et renvoie les 3 prochaines occurrences.

    Utilisé par l'UI pour le preview live à la saisie. Aucun accès DB.
    """
    return JSONResponse(svc.validate_cron(body.cron_expression).to_dict())
