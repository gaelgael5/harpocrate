"""Endpoints /v1/admin/cultures — cultures activables (épic « Cultures et templates
Listmonk paramétrés en base », feature 1).

- GET   /v1/admin/cultures          — toutes les langues ISO 639-1
- PATCH /v1/admin/cultures/{code}   — activer / désactiver, désigner la culture par défaut

Pas de création ni de suppression : la liste ISO 639-1 est amorcée par la migration 034.
Tous les endpoints exigent le rôle admin et écrivent une ligne d'audit en cas de modification.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.models.api.cultures import (
    CULTURE_CODE_PATTERN,
    CultureItem,
    CultureListResponse,
    CultureUpdate,
)
from app.services import cultures as svc

router = APIRouter(prefix="/admin/cultures", tags=["admin-cultures"])

CultureCode = Annotated[str, Path(pattern=CULTURE_CODE_PATTERN)]


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("", response_model=CultureListResponse)
async def list_cultures(admin: AdminJwt) -> CultureListResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await svc.list_cultures(conn)
    return CultureListResponse(items=[CultureItem.model_validate(r.model_dump()) for r in rows])


@router.patch("/{code}", response_model=CultureItem)
async def update_culture(
    code: CultureCode, body: CultureUpdate, admin: AdminJwt, request: Request
) -> CultureItem:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await svc.update_culture(
            conn,
            code,
            enabled=body.enabled,
            make_default=body.is_default is True,
            actor_user_id=admin.user_id,
            actor_ip=_client_ip(request),
        )
    return CultureItem.model_validate(row.model_dump())
