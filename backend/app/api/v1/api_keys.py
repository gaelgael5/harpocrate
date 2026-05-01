"""Endpoints /v1/wallets/{wallet_id}/api-keys/* — LOT_08.

NOTE SÉCURITÉ :
- Ces endpoints sont réservés aux JWT uniquement (pas d'API key).
- Le body de création contient auth_secret (en transit uniquement) — JAMAIS loggé.
- L'Authorization header n'est JAMAIS loggé.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.models.api.api_keys import ApiKeyCreateRequest, ApiKeyPatchRequest
from app.services import api_keys as api_keys_svc

router = APIRouter(
    prefix="/wallets/{wallet_id}/api-keys",
    tags=["api-keys"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── GET /v1/wallets/{wallet_id}/api-keys ─────────────────────────────────────


@router.get("")
async def list_api_keys(
    wallet_id: UUID,
    current_user: JwtUser,
) -> JSONResponse:
    """Liste les API keys du wallet. Requiert JWT + [share]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await api_keys_svc.list_api_keys(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── POST /v1/wallets/{wallet_id}/api-keys ────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    wallet_id: UUID,
    req: ApiKeyCreateRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Crée une API key. Body JAMAIS loggé. Requiert JWT + [share].

    Retourne le token complet hrpv_* une seule fois dans la réponse.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await api_keys_svc.create_api_key(
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


# ─── PATCH /v1/wallets/{wallet_id}/api-keys/{api_key_id} ─────────────────────


@router.patch("/{api_key_id}")
async def patch_api_key(
    wallet_id: UUID,
    api_key_id: UUID,
    req: ApiKeyPatchRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Met à jour name/description d'une API key. Requiert JWT + [share].

    On ne peut PAS modifier les permissions (signées dans le HMAC du token).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        await api_keys_svc.update_api_key(
            conn,
            wallet_id=wallet_id,
            api_key_id=api_key_id,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ─── DELETE /v1/wallets/{wallet_id}/api-keys/{api_key_id} ────────────────────


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    wallet_id: UUID,
    api_key_id: UUID,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Révoque une API key (soft delete, revoked_at = NOW()). Requiert JWT + [share]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        await api_keys_svc.revoke_api_key(
            conn,
            wallet_id=wallet_id,
            api_key_id=api_key_id,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
