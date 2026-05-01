"""Endpoint /v1/health — pingue le pool asyncpg."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.pool import get_pool

router = APIRouter()

_VERSION = "0.1.0"


@router.get("/health")
async def health() -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:
        return JSONResponse(
            {"status": "degraded", "version": _VERSION, "db": "unreachable"},
            status_code=503,
        )
    return JSONResponse(
        {"status": "ok", "version": _VERSION, "db": "ok"},
        status_code=200,
    )
