"""Endpoints /v1/admin/connect-clients — registre des applications (feature 1, décision D1).

- GET    /v1/admin/connect-clients        — liste
- POST   /v1/admin/connect-clients        — déclarer une application
- GET    /v1/admin/connect-clients/{id}   — détail
- PATCH  /v1/admin/connect-clients/{id}   — modifier / désactiver (`active=false`)

Pas de suppression : une application se désactive, pour que les API keys qu'elle a obtenues
restent rattachées à une ligne lisible (traçabilité, décision D14).
Tous les endpoints exigent le rôle admin et écrivent une ligne d'audit en cas de modification.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.models.api.connect import (
    ConnectClientCreate,
    ConnectClientItem,
    ConnectClientListResponse,
    ConnectClientUpdate,
)
from app.models.db.connect_client import ConnectClientRow
from app.services import connect_clients as svc

router = APIRouter(prefix="/admin/connect-clients", tags=["admin-connect-clients"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _item(row: ConnectClientRow) -> ConnectClientItem:
    return ConnectClientItem.model_validate(row.model_dump())


@router.get("", response_model=ConnectClientListResponse)
async def list_connect_clients(admin: AdminJwt) -> ConnectClientListResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await svc.list_clients(conn)
    return ConnectClientListResponse(items=[_item(r) for r in rows])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConnectClientItem)
async def create_connect_client(
    body: ConnectClientCreate, admin: AdminJwt, request: Request
) -> ConnectClientItem:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await svc.create_client(
            conn,
            client_id=body.client_id,
            name=body.name,
            description=body.description,
            redirect_uris=body.redirect_uris,
            actor_user_id=admin.user_id,
            actor_ip=_client_ip(request),
        )
    return _item(row)


@router.get("/{client_pk}", response_model=ConnectClientItem)
async def get_connect_client(client_pk: UUID, admin: AdminJwt) -> ConnectClientItem:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await svc.get_client(conn, client_pk)
    return _item(row)


@router.patch("/{client_pk}", response_model=ConnectClientItem)
async def update_connect_client(
    client_pk: UUID, body: ConnectClientUpdate, admin: AdminJwt, request: Request
) -> ConnectClientItem:
    # Seuls les champs effectivement fournis sont modifiés (`description: null` efface).
    changes = body.model_dump(include=body.model_fields_set)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await svc.update_client(
            conn,
            client_pk,
            changes=changes,
            actor_user_id=admin.user_id,
            actor_ip=_client_ip(request),
        )
    return _item(row)
