"""Endpoints /v1/wallets/{wallet_id}/grants/* — LOT_04 / LOT_09."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.models.api.grants import CreateGrantRequest, UpdateGrantRequest
from app.services import grants as grants_svc

router = APIRouter(
    prefix="/wallets/{wallet_id}/grants",
    tags=["grants"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── GET /v1/wallets/{wallet_id}/grants ───────────────────────────────────────


@router.get("")
async def list_grants(
    wallet_id: UUID,
    current_user: JwtUser,
) -> JSONResponse:
    """Liste tous les grants du wallet. Requiert [share]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        result = await grants_svc.list_grants(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── POST /v1/wallets/{wallet_id}/grants ──────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_grant(
    wallet_id: UUID,
    req: CreateGrantRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Crée un grant. Requiert [share] + permissions ⊆ caller."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        result = await grants_svc.create_grant(
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


# ─── PATCH /v1/wallets/{wallet_id}/grants/{grant_id} ─────────────────────────


@router.patch("/{grant_id}")
async def update_grant(
    wallet_id: UUID,
    grant_id: UUID,
    req: UpdateGrantRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Met à jour les permissions d'un grant. Requiert [share] + subset-check."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        await grants_svc.update_grant(
            conn,
            wallet_id=wallet_id,
            grant_id=grant_id,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=None)


# ─── DELETE /v1/wallets/{wallet_id}/grants/{grant_id} ────────────────────────


@router.delete("/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_grant(
    wallet_id: UUID,
    grant_id: UUID,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Supprime un grant. Requiert [share]. Refuse de révoquer le grant owner."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        await grants_svc.delete_grant(
            conn,
            wallet_id=wallet_id,
            grant_id=grant_id,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


# ─── GET /v1/wallets/{wallet_id}/my-grant ────────────────────────────────────
# Note : cet endpoint est séparé du préfixe /grants car il n'est pas sous /grants/{id}
# Il est monté directement sur le wallet router via include_router dans main.py


my_grant_router = APIRouter(
    prefix="/wallets/{wallet_id}",
    tags=["grants"],
)


@my_grant_router.get("/my-grant")
async def get_my_grant(
    wallet_id: UUID,
    current_user: JwtUser,
) -> JSONResponse:
    """Retourne le grant du caller avec encrypted_wallet_key. Lève 404 si absent."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        result = await grants_svc.get_my_grant(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


# ─── GET /v1/wallets/{wallet_id}/my-api-key-grant (LOT_09) ───────────────────
# Endpoint mixte JWT + API key.
# Pour une API key : retourne api_keys.encrypted_wallet_key (chiffrée par decryption_key).
# Pour un JWT : retourne wallet_grants.encrypted_wallet_key (chiffrée par user_private_key).
# Utilisé par le SDK client pour obtenir la wallet_key avant de déchiffrer les secrets.


@my_grant_router.get("/my-api-key-grant")
async def get_my_api_key_grant(
    wallet_id: UUID,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Retourne l'encrypted_wallet_key pour l'API key courante.

    - API key : retourne api_keys.encrypted_wallet_key (chiffrée par decryption_key).
    - JWT : retourne wallet_grants.encrypted_wallet_key du caller.

    Requiert un token valide (API key ou JWT).
    """
    import base64

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_bearer_token", "message": "Bearer token required"},
        )
    token = authorization[7:]

    pool = await get_pool()

    if token.startswith("hrpv_"):
        # Chemin API key
        from app.core.api_key_auth import validate_api_key_token

        api_key_caller = await validate_api_key_token(token, pool=pool)

        # Scope check
        if api_key_caller.wallet_id != wallet_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Wallet not found"},
            )

        # Récupère encrypted_wallet_key depuis api_keys
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT encrypted_wallet_key FROM api_keys WHERE id = $1",
                api_key_caller.api_key_id,
            )

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "api_key_not_found", "message": "API key not found"},
            )

        enc_wk_b64 = base64.b64encode(bytes(row["encrypted_wallet_key"])).decode()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "wallet_id": str(wallet_id),
                "api_key_id": str(api_key_caller.api_key_id),
                "encrypted_wallet_key": enc_wk_b64,
            },
        )
    else:
        # Chemin JWT — délègue à my_grant
        from app.core.security import _validate_jwt

        payload = await _validate_jwt(token)
        async with pool.acquire() as conn:
            user = await users_repo.get_by_keycloak_sub(conn, payload["sub"])
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "first_login", "message": "User must bootstrap first"},
                )
            grant_result = await grants_svc.get_my_grant(
                conn,
                wallet_id=wallet_id,
                caller_user_id=user.id,
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=grant_result.model_dump(mode="json"),
        )
