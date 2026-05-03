"""Endpoints /v1/wallets/{wallet_id}/secrets/* — LOT_05.

NOTE SÉCURITÉ — Body jamais loggé :
  Le middleware log_requests dans app/main.py détecte les chemins /secrets et
  positionne body_logged=False. Aucun handler ne lit ni ne logue request.body().

Auth mixte (JWT ou API key hrpv_*) sur tous les endpoints selon permission requise.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.api_key_auth import AuthContext, require_any_auth_with_any_of_permissions, require_any_auth_with_permission
from app.db.pool import get_pool
from app.db.repositories import secrets as secrets_repo
from app.models.api.secrets import (
    PlaceholderCreateRequest,
    PopulateRequest,
    SecretCreateRequest,
    SecretPatchRequest,
    SecretPutRequest,
)
from app.models.db.secret import SecretRow
from app.services import secrets as secrets_svc
from app.services.permissions import PERM_ADD, PERM_INIT, PERM_READ, PERM_REMOVE, PERM_WRITE
from app.services.secret_paths import normalize_path

router = APIRouter(
    prefix="/wallets/{wallet_id}/secrets",
    tags=["secrets"],
)

# ─── Auth shorthands ──────────────────────────────────────────────────────────

ReadAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_READ))]
AddAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_ADD))]
WriteAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_WRITE))]
InitAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_INIT))]
RemoveAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_REMOVE))]
DescriptorAuth = Annotated[AuthContext, Depends(require_any_auth_with_any_of_permissions(PERM_READ | PERM_INIT))]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _secret_to_dict(s: SecretRow) -> dict[str, object]:
    return {
        "id": str(s.id),
        "wallet_id": str(s.wallet_id),
        "name": s.name,
        "description": s.description,
        "is_placeholder": s.is_placeholder,
        "generation_version": s.generation_version,
        "tags": s.tags,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── GET /v1/wallets/{wallet_id}/secrets ──────────────────────────────────────


@router.get("")
async def list_secrets(
    wallet_id: UUID,
    auth: ReadAuth,
    request: Request,
    path: str | None = Query(default=None, description="Filtrer par répertoire"),
    tag: str | None = Query(default=None),
    name_contains: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
    """Liste les secrets du wallet (sans encrypted_value). Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if path is not None:
            cursor_updated_at, cursor_id = None, None
            if cursor:
                try:
                    cursor_updated_at, cursor_id = secrets_repo.decode_cursor(cursor)
                except ValueError:
                    return JSONResponse(status_code=400, content={"error": "invalid_cursor"})

            normalized = normalize_path(path)
            rows = await secrets_repo.list_by_path(
                conn,
                wallet_id=wallet_id,
                path=normalized,
                limit=limit,
                cursor_updated_at=cursor_updated_at,
                cursor_id=cursor_id,
            )
            next_cursor = None
            if len(rows) == limit:
                last = rows[-1]
                next_cursor = secrets_repo.encode_cursor(last.updated_at, last.id)

            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "secrets": [_secret_to_dict(s) for s in rows],
                    "next_cursor": next_cursor,
                },
            )

        result = await secrets_svc.list_secrets(
            conn,
            wallet_id=wallet_id,
            caller_user_id=auth.caller_user_id,
            limit=limit,
            cursor=cursor,
            tag_filter=tag,
            name_contains=name_contains,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── GET /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────────


@router.get("/{name}")
async def get_secret(
    wallet_id: UUID,
    name: str,
    auth: ReadAuth,
    request: Request,
) -> JSONResponse:
    """Retourne le secret (encrypted_value + encrypted_wallet_key du caller). Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.get_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── POST /v1/wallets/{wallet_id}/secrets ─────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_secret(
    wallet_id: UUID,
    req: SecretCreateRequest,
    auth: AddAuth,
    request: Request,
) -> JSONResponse:
    """Crée un secret. Body JAMAIS loggé (voir middleware log_requests). Requiert [add]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.create_secret(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_201_CREATED, content=result.model_dump(mode="json"))


# ─── PUT /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────────


@router.put("/{name}")
async def put_secret(
    wallet_id: UUID,
    name: str,
    req: SecretPutRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Remplace encrypted_value, incrémente generation_version. Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.put_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── PATCH /v1/wallets/{wallet_id}/secrets/{name} ────────────────────────────


@router.patch("/{name}")
async def patch_secret(
    wallet_id: UUID,
    name: str,
    req: SecretPatchRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Met à jour description/tags uniquement (pas la valeur). Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await secrets_svc.patch_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ─── POST /v1/wallets/{wallet_id}/secrets/placeholder ────────────────────────

# IMPORTANT : cette route doit être déclarée AVANT "/{name}" pour que FastAPI
# ne l'interprète pas comme un secret nommé "placeholder".


@router.post("/placeholder", status_code=status.HTTP_201_CREATED)
async def create_placeholder(
    wallet_id: UUID,
    req: PlaceholderCreateRequest,
    auth: AddAuth,
    request: Request,
) -> JSONResponse:
    """Crée un secret placeholder avec descripteur de génération. Requiert [add]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.create_placeholder(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_201_CREATED, content=result.model_dump(mode="json"))


# ─── POST /v1/wallets/{wallet_id}/secrets/{name}/populate ────────────────────


@router.post("/{name}/populate")
async def populate_secret(
    wallet_id: UUID,
    name: str,
    req: PopulateRequest,
    auth: InitAuth,
    request: Request,
) -> JSONResponse:
    """Peuple un placeholder avec sa valeur chiffrée. Requiert [init]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.populate_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── GET /v1/wallets/{wallet_id}/secrets/{name}/descriptor ───────────────────


@router.get("/{name}/descriptor")
async def get_descriptor(
    wallet_id: UUID,
    name: str,
    auth: DescriptorAuth,
    request: Request,
) -> JSONResponse:
    """Retourne le descripteur de génération du placeholder. Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.get_descriptor(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── DELETE /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    wallet_id: UUID,
    name: str,
    auth: RemoveAuth,
    request: Request,
) -> None:
    """Supprime le secret (cascade sur secret_tags). Requiert [remove]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await secrets_svc.delete_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )
