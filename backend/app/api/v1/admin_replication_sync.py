"""Endpoints /v1/admin/replication/sync/* — réplication MQTT (LOT_21B).

Auth : AdminJwt.

- GET /sync/status — flag enabled, cursor de push, peers connus, lag par peer
- POST /sync/cursor/reset — reset manuel du cursor de push (admin)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.db.repositories import sync_replication as sync_repo
from app.services import sync_replication_service as svc

router = APIRouter(prefix="/admin/replication/sync", tags=["admin-replication-sync"])


@router.get("/status", response_class=JSONResponse)
async def sync_status(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await sync_repo.get_push_cursor(conn)
        states = await sync_repo.list_states(conn)

    publisher = svc.get_publisher()
    consumer = svc.get_consumer()

    return JSONResponse({
        "enabled": settings.sync_enabled,
        "cluster_id": settings.sync_cluster_id,
        "instance_id": settings.instance_id,
        "broker": (
            f"{settings.sync_mqtt_host}:{settings.sync_mqtt_port}"
            if settings.sync_mqtt_host else None
        ),
        "publisher_running": publisher is not None,
        "consumer_running": consumer is not None,
        "push_cursor": cursor,
        "peers": [
            {
                "emitter": row["peer_emitter"],
                "last_applied_seq": int(row["last_applied_seq"]),
                "last_acked_seq": int(row["last_acked_seq"]),
                "last_received_seq": int(row["last_received_seq"]),
                "last_seen_at": (
                    row["last_seen_at"].isoformat() if row["last_seen_at"] else None
                ),
                "status": row["status"],
                "lag": max(
                    0,
                    int(row["last_received_seq"]) - int(row["last_applied_seq"]),
                ),
            }
            for row in states
        ],
    })


class ResetCursorBody(BaseModel):
    new_cursor: int = Field(ge=0)


@router.post("/cursor/reset", response_class=JSONResponse)
async def reset_push_cursor(body: ResetCursorBody, admin: AdminJwt) -> JSONResponse:
    publisher = svc.get_publisher()
    if publisher is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "sync_publisher_not_running"},
        )
    await publisher.reset_cursor(body.new_cursor)
    return JSONResponse({"reset_to": body.new_cursor})
