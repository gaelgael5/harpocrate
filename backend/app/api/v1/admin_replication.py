"""Endpoints /v1/admin/replication/* — LOT_20.

Auth : AdminJwt uniquement.

- GET /strategies — liste les stratégies disponibles + active
- POST /strategies/{id}/activate — bascule la stratégie active
- GET /status — état temps réel (interroge Patroni si stratégie patroni)
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.services import replication as svc

router = APIRouter(prefix="/admin/replication", tags=["admin-replication"])


@router.get("/strategies", response_class=JSONResponse)
async def list_strategies(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        from app.db.repositories import replication_strategies as repo
        rows = await repo.list_strategies(conn)
    return JSONResponse({
        "strategies": [svc.row_to_dict(r) for r in rows],
    })


@router.post(
    "/strategies/{strategy_id}/activate",
    status_code=status.HTTP_200_OK,
    response_class=JSONResponse,
)
async def activate_strategy(strategy_id: UUID, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        ok = await svc.activate(conn, strategy_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "strategy_not_found_or_disabled"},
        )
    return JSONResponse({"activated": True, "strategy_id": str(strategy_id)})


@router.get("/status", response_class=JSONResponse)
async def replication_status(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        active = await svc.get_active(conn)
    if active is None:
        return JSONResponse({"strategy": None, "status": "no_active_strategy"})

    row, strategy = active
    live_status = await strategy.get_status()
    return JSONResponse({
        "strategy": svc.row_to_dict(row),
        "live": live_status,
    })
