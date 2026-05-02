"""Endpoints /v1/wallets/{wallet_id}/secrets/* — LOT_05.

NOTE SÉCURITÉ — Body jamais loggé :
  Le middleware log_requests dans app/main.py détecte les chemins /secrets et
  positionne body_logged=False. Aucun handler ne lit ni ne logue request.body().
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.models.api.secrets import (
    PlaceholderCreateRequest,
    PopulateRequest,
    SecretCreateRequest,
    SecretPatchRequest,
    SecretPutRequest,
)
from app.services import secrets as secrets_svc

router = APIRouter(
    prefix="/wallets/{wallet_id}/secrets",
    tags=["secrets"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── GET /v1/wallets/{wallet_id}/secrets ──────────────────────────────────────


@router.get("")
async def list_secrets(
    wallet_id: UUID,
    current_user: JwtUser,
    request: Request,
    tag: str | None = Query(default=None),
    name_contains: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
    """Liste les secrets du wallet (sans encrypted_value). Requiert un grant."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.list_secrets(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
            limit=limit,
            cursor=cursor,
            tag_filter=tag,
            name_contains=name_contains,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── GET /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────────


@router.get("/{name}")
async def get_secret(
    wallet_id: UUID,
    name: str,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Retourne le secret (encrypted_value + encrypted_wallet_key du caller). Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.get_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── POST /v1/wallets/{wallet_id}/secrets ─────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_secret(
    wallet_id: UUID,
    req: SecretCreateRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Crée un secret. Body JAMAIS loggé (voir middleware log_requests). Requiert [add]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.create_secret(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=result.model_dump(mode="json"),
    )


# ─── PUT /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────────


@router.put("/{name}")
async def put_secret(
    wallet_id: UUID,
    name: str,
    req: SecretPutRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Remplace encrypted_value, incrémente generation_version.

    Body JAMAIS loggé (voir middleware log_requests). Requiert [write].
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.put_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── PATCH /v1/wallets/{wallet_id}/secrets/{name} ────────────────────────────


@router.patch("/{name}")
async def patch_secret(
    wallet_id: UUID,
    name: str,
    req: SecretPatchRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Met à jour description/tags uniquement (pas la valeur). Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        await secrets_svc.patch_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=user.id,
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
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Crée un secret placeholder avec descripteur de génération. Requiert [add]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.create_placeholder(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=result.model_dump(mode="json"),
    )


# ─── POST /v1/wallets/{wallet_id}/secrets/{name}/populate ────────────────────


@router.post("/{name}/populate")
async def populate_secret(
    wallet_id: UUID,
    name: str,
    req: PopulateRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Peuple un placeholder avec sa valeur chiffrée. Requiert [init]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.populate_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── GET /v1/wallets/{wallet_id}/secrets/{name}/descriptor ───────────────────


@router.get("/{name}/descriptor")
async def get_descriptor(
    wallet_id: UUID,
    name: str,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Retourne le descripteur de génération du placeholder. Requiert [read] ou [init]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await secrets_svc.get_descriptor(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── DELETE /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    wallet_id: UUID,
    name: str,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Supprime le secret (cascade sur secret_tags). Requiert [remove]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        await secrets_svc.delete_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
