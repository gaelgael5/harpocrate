"""Endpoints /v1/audit-log/* — LOT_10.

GET /v1/audit-log          — JWT ou API key (visibilité différenciée)
GET /v1/audit-log/actions  — JWT uniquement (liste des actions distinctes)
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.core.api_key_auth import ApiKeyCaller, validate_api_key_token
from app.core.security import CurrentUser, _validate_jwt
from app.db.pool import get_pool
from app.db.repositories import audit_log as audit_log_repo
from app.db.repositories import users as users_repo
from app.models.api.audit_log import (
    AuditLogActionsResponse,
    AuditLogFilters,
    AuditLogResponse,
)
from app.services import audit_log as audit_log_svc

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


# ─── Dependency mixte JWT ou API key ─────────────────────────────────────────


class _AuditCaller:
    """Résultat de l'authentification pour les endpoints audit-log."""

    __slots__ = ("api_key_id", "jwt_user_id")

    def __init__(
        self,
        *,
        jwt_user_id: UUID | None = None,
        api_key_id: UUID | None = None,
    ) -> None:
        self.jwt_user_id = jwt_user_id
        self.api_key_id = api_key_id


async def _require_jwt_or_api_key(
    authorization: Annotated[str | None, Header()] = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> _AuditCaller:
    """Dependency : accepte JWT Keycloak ou API key hrpv_*."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_bearer_token",
                "message": "Authorization header with Bearer token required",
            },
        )
    token = authorization[7:]

    if token.startswith("hrpv_"):
        caller: ApiKeyCaller = await validate_api_key_token(token, pool=pool)
        return _AuditCaller(api_key_id=caller.api_key_id)

    # JWT path
    payload = await _validate_jwt(token)
    jwt_user = CurrentUser(
        keycloak_sub=payload["sub"],
        email=payload.get("email", ""),
        display_name=payload.get("name"),
    )
    async with pool.acquire() as conn:
        user_row = await users_repo.get_by_keycloak_sub(conn, jwt_user.keycloak_sub)
    if user_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "first_login", "message": "User must bootstrap first"},
        )
    return _AuditCaller(jwt_user_id=user_row.id)


AuditAuth = Annotated[_AuditCaller, Depends(_require_jwt_or_api_key)]


# ─── GET /v1/audit-log ────────────────────────────────────────────────────────


@router.get("")
async def list_audit_log(
    caller: AuditAuth,
    wallet_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    action_prefix: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
    actor_api_key_id: UUID | None = Query(default=None),
    target_secret_id: UUID | None = Query(default=None),
    success: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
    """Retourne les événements d'audit visibles par le caller.

    - JWT : ses propres actions + actions sur ses wallets owned.
    - API key : uniquement ses propres actions (filtre forcé).
    """
    filters = AuditLogFilters(
        wallet_id=wallet_id,
        action=action,
        action_prefix=action_prefix,
        since=since,
        until=until,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
        target_secret_id=target_secret_id,
        success=success,
        limit=limit,
        cursor=cursor,
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        if caller.api_key_id is not None:
            result: AuditLogResponse = await audit_log_svc.query_audit_log_for_api_key(
                conn,
                api_key_id=caller.api_key_id,
                filters=filters,
            )
        else:
            assert caller.jwt_user_id is not None
            result = await audit_log_svc.query_audit_log_for_jwt(
                conn,
                user_id=caller.jwt_user_id,
                filters=filters,
            )

    return JSONResponse(content=result.model_dump(mode="json"))


# ─── GET /v1/audit-log/actions ────────────────────────────────────────────────


@router.get("/actions")
async def list_audit_actions(
    caller: AuditAuth,
) -> JSONResponse:
    """Retourne la liste des actions distinctes présentes dans audit_log.

    Accessible par JWT ou API key — utile pour peupler les dropdowns UI.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        actions = await audit_log_repo.get_distinct_actions(conn)

    response = AuditLogActionsResponse(actions=actions)
    return JSONResponse(content=response.model_dump(mode="json"))
