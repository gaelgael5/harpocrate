"""Endpoints /v1/admin/maintenance/* — LOT_12A."""
from __future__ import annotations

import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.core.maintenance import maintenance_state
from app.db.pool import get_pool
from app.db.repositories import system_metadata as meta_repo

router = APIRouter(prefix="/admin/maintenance", tags=["admin-maintenance"])


@router.get("/status", include_in_schema=True)
async def maintenance_status() -> JSONResponse:
    """Retourne l'état actuel du mode maintenance (public, sans auth)."""
    return JSONResponse({
        "active": maintenance_state.active,
        "reason": maintenance_state.reason,
        "started_at": maintenance_state.started_at.isoformat() if maintenance_state.started_at else None,
        "effective_at": maintenance_state.effective_at.isoformat() if maintenance_state.effective_at else None,
        "estimated_end_at": maintenance_state.estimated_end_at.isoformat() if maintenance_state.estimated_end_at else None,
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
    """Active le mode maintenance. Requiert le rôle harpocrate-admin."""
    now = datetime.datetime.now(datetime.UTC)
    effective = now + datetime.timedelta(seconds=body.delay_seconds)
    estimated_end = (
        effective + datetime.timedelta(minutes=body.estimated_duration_minutes)
        if body.estimated_duration_minutes > 0
        else None
    )

    maintenance_state.active = True
    maintenance_state.reason = body.reason
    maintenance_state.started_at = now
    maintenance_state.effective_at = effective
    maintenance_state.estimated_end_at = estimated_end

    pool = await get_pool()
    async with pool.acquire() as conn:
        await meta_repo.set_value(conn, "maintenance_mode", {
            "active": True,
            "reason": body.reason,
            "started_at": now.isoformat(),
        })

    return JSONResponse({
        "active": True,
        "reason": body.reason,
        "started_at": now.isoformat(),
        "effective_at": effective.isoformat(),
        "estimated_end_at": estimated_end.isoformat() if estimated_end else None,
    })


@router.post("/disable")
async def maintenance_disable(admin: AdminJwt) -> JSONResponse:
    """Désactive le mode maintenance."""
    maintenance_state.active = False
    maintenance_state.reason = None
    maintenance_state.started_at = None
    maintenance_state.effective_at = None
    maintenance_state.estimated_end_at = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        await meta_repo.set_value(conn, "maintenance_mode", {"active": False})

    return JSONResponse({"active": False})
