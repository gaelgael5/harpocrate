"""Endpoints /v1/admin/maintenance/* — LOT_12A + LOT_21A (NOTIFY cluster)."""
from __future__ import annotations

import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.core.cluster_state import cluster_state
from app.core.maintenance import maintenance_state
from app.db.pool import get_pool
from app.db.repositories import system_metadata as meta_repo
from app.services.cluster_notify import notify_maintenance_changed

router = APIRouter(prefix="/admin/maintenance", tags=["admin-maintenance"])


@router.get("/status", include_in_schema=True)
async def maintenance_status() -> JSONResponse:
    """Retourne l'état actuel du mode maintenance (public, sans auth).

    Reflète `cluster_state` (synchronisé via LISTEN/NOTIFY) plutôt que le
    singleton local — cohérent multi-nœuds.
    """
    return JSONResponse({
        "active": cluster_state.maintenance_active,
        "reason": cluster_state.maintenance_reason,
        "started_at": (
            cluster_state.maintenance_started_at.isoformat()
            if cluster_state.maintenance_started_at else None
        ),
        "effective_at": (
            cluster_state.maintenance_effective_at.isoformat()
            if cluster_state.maintenance_effective_at else None
        ),
        "estimated_end_at": (
            cluster_state.maintenance_estimated_end_at.isoformat()
            if cluster_state.maintenance_estimated_end_at else None
        ),
    })


class EnableBody(BaseModel):
    reason: str = "Maintenance in progress"
    delay_seconds: int = Field(default=0, ge=0)
    estimated_duration_minutes: int = Field(default=0, ge=0)


@router.post("/enable")
async def maintenance_enable(
    body: EnableBody,
    admin: AdminJwt,
) -> JSONResponse:
    """Active le mode maintenance et notifie tout le cluster."""
    now = datetime.datetime.now(datetime.UTC)
    effective = now + datetime.timedelta(seconds=body.delay_seconds)
    estimated_end = (
        effective + datetime.timedelta(minutes=body.estimated_duration_minutes)
        if body.estimated_duration_minutes > 0
        else None
    )

    payload: dict[str, object] = {
        "active": True,
        "reason": body.reason,
        "started_at": now.isoformat(),
        "effective_at": effective.isoformat(),
        "estimated_end_at": estimated_end.isoformat() if estimated_end else None,
    }

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
            await meta_repo.set_value(conn, "maintenance_mode", payload)
            # NOTIFY dans la même transaction → si rollback, pas de notif (LOT_21A).
            await notify_maintenance_changed(conn, active=True)

    # Mise à jour locale immédiate (le NOTIFY back-fillera les autres nœuds).
    cluster_state.maintenance_active = True
    cluster_state.maintenance_reason = body.reason
    cluster_state.maintenance_started_at = now
    cluster_state.maintenance_effective_at = effective
    cluster_state.maintenance_estimated_end_at = estimated_end
    # Compat legacy.
    maintenance_state.active = True
    maintenance_state.reason = body.reason
    maintenance_state.started_at = now
    maintenance_state.effective_at = effective
    maintenance_state.estimated_end_at = estimated_end

    return JSONResponse({
        "active": True,
        "reason": body.reason,
        "started_at": now.isoformat(),
        "effective_at": effective.isoformat(),
        "estimated_end_at": estimated_end.isoformat() if estimated_end else None,
    })


@router.post("/disable")
async def maintenance_disable(admin: AdminJwt) -> JSONResponse:
    """Désactive le mode maintenance et notifie tout le cluster."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
            await meta_repo.set_value(conn, "maintenance_mode", {"active": False})
            await notify_maintenance_changed(conn, active=False)

    cluster_state.maintenance_active = False
    cluster_state.maintenance_reason = None
    cluster_state.maintenance_started_at = None
    cluster_state.maintenance_effective_at = None
    cluster_state.maintenance_estimated_end_at = None
    maintenance_state.active = False
    maintenance_state.reason = None
    maintenance_state.started_at = None
    maintenance_state.effective_at = None
    maintenance_state.estimated_end_at = None

    return JSONResponse({"active": False})
