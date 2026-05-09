"""Endpoints /v1/wallets/* — CRUD wallets, transfer ownership, export/import, tree."""
from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import secrets as secrets_repo
from app.db.repositories import users as users_repo
from app.db.repositories import wallets as wallets_repo
from app.models.api.exports import WalletImportRequest
from app.models.api.wallets import (
    TransferOwnershipRequest,
    WalletCreateRequest,
    WalletCreateResponse,
    WalletItem,
    WalletListResponse,
    WalletPatchRequest,
)
from app.models.db.wallet import WalletWithGrant
from app.services import wallets as wallets_svc
from app.services.permissions import PERM_READ, has
from app.services.secret_paths import normalize_path

_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_\-]")

router = APIRouter(prefix="/wallets", tags=["wallets"])


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _wallet_item(w: WalletWithGrant, caller_user_id: UUID) -> WalletItem:
    return WalletItem(
        id=w.id,
        name=w.name,
        description=w.description,
        tags=sorted(w.tags),
        owner_user_id=w.owner_user_id,
        is_owner=w.owner_user_id == caller_user_id,
        my_permissions=w.my_permissions,
        valued_secrets_count=w.valued_secrets_count,
        placeholder_secrets_count=w.placeholder_secrets_count,
        created_at=w.created_at,
        updated_at=w.updated_at,
        deleted_at=w.deleted_at,
        environment_id=w.environment_id,
    )


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── GET /v1/wallets ──────────────────────────────────────────────────────────


@router.get("")
async def list_wallets(
    current_user: JwtUser,
    request: Request,
    tag: str | None = Query(default=None),
    name_contains: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
    """Liste les wallets accessibles par le caller, avec pagination cursor-based."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        wallets, next_cursor, deleted_wallets = await wallets_svc.list_wallets(
            conn,
            caller_user_id=user.id,
            limit=limit,
            cursor=cursor,
            tag_filter=tag,
            name_contains=name_contains,
        )

    items = [_wallet_item(w, user.id) for w in wallets]
    deleted_items = [_wallet_item(w, user.id) for w in deleted_wallets]
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=WalletListResponse(
            wallets=items,
            next_cursor=next_cursor,
            deleted_wallets=deleted_items,
        ).model_dump(mode="json"),
    )


# ─── POST /v1/wallets ─────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_wallet(
    req: WalletCreateRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Crée un wallet et le grant owner (permissions=63)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        wallet_id = await wallets_svc.create_wallet(
            conn,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=WalletCreateResponse(wallet_id=wallet_id).model_dump(mode="json"),
    )


# ─── GET /v1/wallets/{id} ─────────────────────────────────────────────────────


@router.get("/{wallet_id}")
async def get_wallet(
    wallet_id: UUID,
    current_user: JwtUser,
) -> JSONResponse:
    """Retourne le wallet si le caller y a un grant (404 sinon)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        wallet = await wallets_svc.get_wallet(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_wallet_item(wallet, user.id).model_dump(mode="json"),
    )


# ─── PATCH /v1/wallets/{id} ───────────────────────────────────────────────────


@router.patch("/{wallet_id}")
async def patch_wallet(
    wallet_id: UUID,
    req: WalletPatchRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Mise à jour partielle nom/description/tags."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        updated = await wallets_svc.patch_wallet(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_wallet_item(updated, user.id).model_dump(mode="json"),
    )


# ─── DELETE /v1/wallets/{id} ──────────────────────────────────────────────────


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_wallet(
    wallet_id: UUID,
    current_user: JwtUser,
    request: Request,
) -> Response:
    """Suppression logique du wallet. Purge physique automatique 24h après."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        await wallets_svc.delete_wallet(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{wallet_id}/restore", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def restore_wallet(
    wallet_id: UUID,
    current_user: JwtUser,
    request: Request,
) -> Response:
    """Annule la suppression logique (dans la fenêtre de 24h)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        await wallets_svc.restore_wallet(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── POST /v1/wallets/{id}/transfer-ownership ─────────────────────────────────


@router.post("/{wallet_id}/transfer-ownership")
async def transfer_ownership(
    wallet_id: UUID,
    req: TransferOwnershipRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Transfère l'ownership au new_owner (doit avoir un grant existant)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        updated = await wallets_svc.transfer_ownership(
            conn,
            wallet_id=wallet_id,
            new_owner_user_id=req.new_owner_user_id,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_wallet_item(updated, user.id).model_dump(mode="json"),
    )


# ─── GET /v1/wallets/{id}/tree ───────────────────────────────────────────────


@router.get("/{wallet_id}/tree")
async def get_wallet_tree(
    wallet_id: UUID,
    current_user: JwtUser,
    path: str = Query(default="/", description="Répertoire à explorer"),
) -> JSONResponse:
    """Retourne les sous-répertoires directs d'un path + compte de secrets. Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        wallet = await wallets_repo.get_wallet_for_user(
            conn, wallet_id=wallet_id, user_id=user.id
        )
        if wallet is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "wallet_not_found", "message": "Wallet not found"},
            )
        if not has(wallet.my_permissions, PERM_READ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "forbidden", "message": "Permission [read] required"},
            )

        normalized = normalize_path(path)
        result = await secrets_repo.get_tree_data(conn, wallet_id=wallet_id, path=normalized)

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# ─── GET /v1/wallets/{id}/export ─────────────────────────────────────────────


@router.get("/{wallet_id}/export")
async def export_wallet(
    wallet_id: UUID,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Exporte la structure du wallet en JSON versionné (sans valeurs chiffrées).

    Requiert JWT uniquement (pas d'API keys) et permission [read].
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        export = await wallets_svc.export_wallet(
            conn,
            wallet_id=wallet_id,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    payload = export.model_dump(mode="json")
    safe_name = _UNSAFE_FILENAME_RE.sub("_", export.wallet.name)[:64]
    date_str = export.exported_at.strftime("%Y%m%d") if export.exported_at else "export"
    filename = f"vault-{safe_name}-{date_str}.json"

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── POST /v1/wallets/import ─────────────────────────────────────────────────


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_wallet(
    req: WalletImportRequest,
    current_user: JwtUser,
    request: Request,
) -> JSONResponse:
    """Importe un wallet depuis une structure exportée. Atomique.

    Requiert JWT uniquement (pas d'API keys).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        result = await wallets_svc.import_wallet(
            conn,
            req=req,
            caller_user_id=user.id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=result.model_dump(mode="json"),
    )
