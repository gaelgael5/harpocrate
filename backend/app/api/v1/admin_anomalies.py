"""Endpoints admin pour la supervision des anomalies + sessions de recovery (LOT_57).

Vue agrégée que l'admin utilise pour réagir :
- `GET /v1/admin/anomalies` — toutes les anomalies, tous users confondus
- `POST /v1/admin/anomalies/{id}/ack` — acquitte une anomalie
- `GET /v1/admin/recovery-sessions` — liste paginée des sessions de recovery
  (utile pour repérer une vague d'attaques en cours)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.db.repositories import anomalies as anomalies_repo

router = APIRouter(prefix="/admin", tags=["admin-anomalies"])


@router.get("/anomalies")
async def list_anomalies(
    admin: AdminJwt,
    only_unacknowledged: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await anomalies_repo.list_all(
            conn,
            only_unacknowledged=only_unacknowledged,
            limit=limit,
        )
    return JSONResponse(
        {
            "anomalies": [
                {
                    "id": r.id,
                    "user_id": str(r.user_id),
                    "detected_at": r.detected_at.isoformat(),
                    "severity": r.severity,
                    "anomaly_type": r.anomaly_type,
                    "metadata": r.metadata,
                    "acknowledged_at": r.acknowledged_at.isoformat()
                    if r.acknowledged_at
                    else None,
                    "acknowledged_by_user_id": str(r.acknowledged_by_user_id)
                    if r.acknowledged_by_user_id
                    else None,
                }
                for r in rows
            ]
        }
    )


@router.post("/anomalies/{anomaly_id}/ack")
async def acknowledge_anomaly(anomaly_id: int, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        ok = await anomalies_repo.acknowledge_admin(
            conn, anomaly_id, by_user_id=admin.user_id
        )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "anomaly_not_found_or_already_ack"},
        )
    return JSONResponse({"acknowledged": True})


@router.get("/recovery-sessions")
async def list_recovery_sessions(
    admin: AdminJwt,
    limit: int = Query(default=100, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
) -> JSONResponse:
    """Liste les sessions de recovery récentes pour supervision."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if status_filter is not None:
            if status_filter not in ("pending", "consumed", "failed", "expired"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "invalid_status_filter"},
                )
            rows = await conn.fetch(
                """
                SELECT id, user_id, email, created_at, expires_at, status,
                       attempts, ip_started, ip_consumed, consumed_at
                FROM recovery_sessions
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status_filter,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, user_id, email, created_at, expires_at, status,
                       attempts, ip_started, ip_consumed, consumed_at
                FROM recovery_sessions
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
    return JSONResponse(
        {
            "sessions": [
                {
                    "id": str(r["id"]),
                    "user_id": str(r["user_id"]) if r["user_id"] else None,
                    "email": r["email"],
                    "created_at": r["created_at"].isoformat(),
                    "expires_at": r["expires_at"].isoformat(),
                    "status": r["status"],
                    "attempts": r["attempts"],
                    "ip_started": str(r["ip_started"]) if r["ip_started"] else None,
                    "ip_consumed": str(r["ip_consumed"]) if r["ip_consumed"] else None,
                    "consumed_at": r["consumed_at"].isoformat()
                    if r["consumed_at"]
                    else None,
                }
                for r in rows
            ]
        }
    )


def _safe_uuid(v: object) -> UUID | None:
    if v is None:
        return None
    return UUID(str(v))
