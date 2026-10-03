"""Endpoints /v1/connect/* — flux « Se connecter avec Harpocrate » (features 2 à 5).

- POST /v1/connect/par                         — dépôt de la demande par l'application (PAR)
- GET  /v1/connect/requests/{request_uri}      — lecture de la demande pour le consentement

Le dépôt n'est pas authentifié (décision D7) : il est limité en débit, et toute la
validation (application active, URL de retour exacte) a lieu avant de répondre. Les routes
appelées par le navigateur exigent une session Keycloak ; l'admin local en est exclu (D10).
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.core.rate_limit import rate_limit_dep
from app.core.security import OidcUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.models.api.connect import CLIENT_ID_PATTERN
from app.models.api.connect_flow import (
    REQUEST_URI_PATTERN,
    AppPublicJwk,
    ConnectClientPublic,
    ConnectParRequest,
    ConnectParResponse,
    ConnectRequestView,
)
from app.services import connect_requests as svc

router = APIRouter(prefix="/connect", tags=["connect"])

RequestUri = Path(pattern=REQUEST_URI_PATTERN)
ClientIdQuery = Query(pattern=CLIENT_ID_PATTERN)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@router.post(
    "/par",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectParResponse,
    dependencies=[Depends(rate_limit_dep("30/minute;300/hour"))],
)
async def push_authorization_request(
    body: ConnectParRequest, request: Request
) -> ConnectParResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        request_uri = await svc.create_request(
            conn, body=body, now=_now(), actor_ip=_client_ip(request)
        )
    return ConnectParResponse(request_uri=request_uri, expires_in=svc.PENDING_TTL_SECONDS)


@router.get("/requests/{request_uri}", response_model=ConnectRequestView)
async def get_connect_request(
    current_user: OidcUser,
    request_uri: str = RequestUri,
    client_id: str = ClientIdQuery,
) -> ConnectRequestView:
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            raise svc.first_login_required()
        row = await svc.open_request(
            conn, request_uri=request_uri, client_id=client_id, user_id=user.id, now=_now()
        )
    return ConnectRequestView(
        client=ConnectClientPublic(
            client_id=row.client_id, name=row.client_name, description=row.client_description
        ),
        redirect_uri=row.redirect_uri,
        requested_permissions=row.requested_permissions,
        requested_ttl_days=row.requested_ttl_days,
        app_public_jwk=AppPublicJwk.model_validate(row.app_public_jwk),
        expires_at=row.expires_at,
    )
