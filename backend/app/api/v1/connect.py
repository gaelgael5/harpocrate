"""Endpoints /v1/connect/* — flux « Se connecter avec Harpocrate » (features 2 à 5).

- POST /v1/connect/par                         — dépôt de la demande par l'application (PAR)
- GET  /v1/connect/requests/{request_uri}      — lecture de la demande pour le consentement
- POST /v1/connect/requests/{request_uri}/deny — refus de l'utilisateur (`access_denied`)
- POST /v1/connect/requests/{request_uri}/api-key — création de la clé SANS dkey (D4)
- POST /v1/connect/requests/{request_uri}/sealed  — dépôt du scellé, émission du code
- POST /v1/connect/token                       — échange du code par l'application (D2)

Le dépôt et l'échange ne sont pas authentifiés (décision D7) : il est limité en débit, et toute la
validation (application active, URL de retour exacte) a lieu avant de répondre. Les routes
appelées par le navigateur exigent une session Keycloak ; l'admin local en est exclu (D10).
"""

from __future__ import annotations

import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.core.rate_limit import rate_limit_dep
from app.core.security import CurrentUser, OidcUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.models.api.connect import CLIENT_ID_PATTERN
from app.models.api.connect_flow import (
    REQUEST_URI_PATTERN,
    AppPublicJwk,
    ConnectApiKeyCreate,
    ConnectApiKeyResponse,
    ConnectClientPublic,
    ConnectParRequest,
    ConnectParResponse,
    ConnectRedirectResponse,
    ConnectRequestView,
    ConnectSealRequest,
    ConnectTokenRequest,
    ConnectTokenResponse,
)
from app.services import connect_exchange, connect_keys
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


async def _user_id(conn: asyncpg.Connection[asyncpg.Record], current_user: CurrentUser) -> UUID:
    user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
    if user is None:
        raise svc.first_login_required()
    return user.id


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
        row = await svc.open_request(
            conn,
            request_uri=request_uri,
            client_id=client_id,
            user_id=await _user_id(conn, current_user),
            now=_now(),
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


@router.post("/requests/{request_uri}/deny", response_model=ConnectRedirectResponse)
async def deny_connect_request(
    current_user: OidcUser,
    request: Request,
    request_uri: str = RequestUri,
    client_id: str = ClientIdQuery,
) -> ConnectRedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        redirect_to = await svc.deny_request(
            conn,
            request_uri=request_uri,
            client_id=client_id,
            user_id=await _user_id(conn, current_user),
            now=_now(),
            actor_ip=_client_ip(request),
        )
    return ConnectRedirectResponse(redirect_to=redirect_to)


@router.post(
    "/requests/{request_uri}/api-key",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectApiKeyResponse,
)
async def create_connect_api_key(
    body: ConnectApiKeyCreate,
    current_user: OidcUser,
    request: Request,
    request_uri: str = RequestUri,
    client_id: str = ClientIdQuery,
) -> ConnectApiKeyResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await connect_keys.create_connect_api_key(
            conn,
            request_uri=request_uri,
            client_id=client_id,
            body=body,
            user_id=await _user_id(conn, current_user),
            now=_now(),
            actor_ip=_client_ip(request),
        )


@router.post("/requests/{request_uri}/sealed", response_model=ConnectRedirectResponse)
async def seal_connect_request(
    body: ConnectSealRequest,
    current_user: OidcUser,
    request: Request,
    request_uri: str = RequestUri,
    client_id: str = ClientIdQuery,
) -> ConnectRedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        redirect_to = await connect_keys.seal_request(
            conn,
            request_uri=request_uri,
            client_id=client_id,
            jwe=body.jwe,
            user_id=await _user_id(conn, current_user),
            now=_now(),
            actor_ip=_client_ip(request),
        )
    return ConnectRedirectResponse(redirect_to=redirect_to)


@router.post(
    "/token",
    response_model=ConnectTokenResponse,
    dependencies=[Depends(rate_limit_dep("30/minute;300/hour"))],
)
async def exchange_connect_code(
    body: ConnectTokenRequest, request: Request
) -> ConnectTokenResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await connect_exchange.exchange_code(
            conn, body=body, now=_now(), actor_ip=_client_ip(request)
        )
