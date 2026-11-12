"""Endpoints /v1/admin/listmonk — templates Listmonk par culture (épic « Cultures et
templates Listmonk paramétrés en base », feature 2).

- GET    /v1/admin/listmonk                                        — connexion + templates
- PUT    /v1/admin/listmonk/connection                             — régler la connexion
- POST   /v1/admin/listmonk/connection/test                        — tester avant d'enregistrer
- PUT    /v1/admin/listmonk/templates/{purpose}/{culture_code}     — poser un ID de template
- DELETE /v1/admin/listmonk/templates/{purpose}/{culture_code}     — retirer un template

Le token Listmonk n'est jamais renvoyé (feature 3) : il s'écrit, il ne se relit pas.
Tous les endpoints exigent le rôle admin et écrivent une ligne d'audit en cas de modification.
"""

from __future__ import annotations

from typing import Annotated, get_args

from fastapi import APIRouter, Path, Request, Response, status

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.models.api.cultures import CULTURE_CODE_PATTERN
from app.models.api.listmonk import (
    ListmonkConnectionUpdate,
    ListmonkSettingsResponse,
    ListmonkTemplateItem,
    ListmonkTemplateUpdate,
    Purpose,
)
from app.services import listmonk_connection as connection_svc
from app.services import listmonk_templates as svc
from app.services.listmonk_connection import ConnectionTestResult

router = APIRouter(prefix="/admin/listmonk", tags=["admin-listmonk"])

CultureCode = Annotated[str, Path(pattern=CULTURE_CODE_PATTERN)]


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("", response_model=ListmonkSettingsResponse)
async def get_listmonk_settings(admin: AdminJwt) -> ListmonkSettingsResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await svc.list_templates(conn)
        connection = await connection_svc.get_connection_view(conn)
    return ListmonkSettingsResponse(
        connection=connection,
        purposes=list(get_args(Purpose)),
        templates=[ListmonkTemplateItem.model_validate(r.model_dump()) for r in rows],
    )


@router.put("/connection", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def set_listmonk_connection(
    body: ListmonkConnectionUpdate, admin: AdminJwt, request: Request
) -> Response:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await connection_svc.save_connection(
            conn,
            url=body.url,
            api_user=body.api_user,
            token=body.token,
            actor_user_id=admin.user_id,
            actor_ip=_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connection/test", response_model=ConnectionTestResult)
async def test_listmonk_connection(
    body: ListmonkConnectionUpdate, admin: AdminJwt
) -> ConnectionTestResult:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await connection_svc.resolve_test_connection(
            conn, url=body.url, api_user=body.api_user, token=body.token
        )


@router.put("/templates/{purpose}/{culture_code}", response_model=ListmonkTemplateItem)
async def set_listmonk_template(
    purpose: Purpose,
    culture_code: CultureCode,
    body: ListmonkTemplateUpdate,
    admin: AdminJwt,
    request: Request,
) -> ListmonkTemplateItem:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await svc.set_template(
            conn,
            purpose=purpose,
            culture_code=culture_code,
            template_id=body.template_id,
            actor_user_id=admin.user_id,
            actor_ip=_client_ip(request),
        )
    return ListmonkTemplateItem.model_validate(row.model_dump())


@router.delete(
    "/templates/{purpose}/{culture_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_listmonk_template(
    purpose: Purpose, culture_code: CultureCode, admin: AdminJwt, request: Request
) -> Response:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await svc.delete_template(
            conn,
            purpose=purpose,
            culture_code=culture_code,
            actor_user_id=admin.user_id,
            actor_ip=_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
