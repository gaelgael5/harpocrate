"""Endpoint WebSocket — bridge SSH terminal pour l'UI admin (LOT 1)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query, WebSocket, status

from app.core.config import settings
from app.core.security import _validate_jwt
from app.db.pool import get_pool
from app.services import admin_user_resolver
from app.services import ssh_terminal as svc

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/ssh-terminal", tags=["admin-ssh-terminal"])


@router.websocket("/ws")
async def ssh_terminal_ws(ws: WebSocket, token: str = Query(...)) -> None:
    if token.startswith("hrpv_"):
        logger.warning(
            "ws_auth_rejected",
            reason="api_key_not_allowed",
            remote=ws.client.host if ws.client else None,
        )
        await ws.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="api_key_not_allowed",
        )
        return
    try:
        payload = await _validate_jwt(token)
    except Exception:
        logger.warning(
            "ws_auth_rejected",
            reason="invalid_token",
            remote=ws.client.host if ws.client else None,
        )
        await ws.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="invalid_token",
        )
        return

    roles = payload.get("realm_access", {}).get("roles", [])
    if settings.admin_role_name not in roles:
        logger.warning(
            "ws_auth_rejected",
            reason="not_admin",
            sub=payload.get("sub"),
            remote=ws.client.host if ws.client else None,
        )
        await ws.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="not_admin",
        )
        return

    try:
        user_id = await admin_user_resolver.resolve_admin_user_id(
            keycloak_sub=payload["sub"],
            email=payload.get("email", ""),
            display_name=payload.get("name"),
        )
    except Exception:
        logger.exception("ws_auth_db_error")
        await ws.close(
            code=status.WS_1011_INTERNAL_ERROR,
            reason="internal_error",
        )
        return
    await ws.accept()

    # `resolve_admin_user_id` above acquires its own transient pool connection.
    # Below we acquire a separate long-lived one held for the WS session duration.
    pool = await get_pool()
    async with pool.acquire() as conn:
        await svc.run_session(
            ws,
            conn,
            actor_user_id=user_id,
            idle_timeout_seconds=settings.ssh_terminal_idle_timeout_seconds,
        )
