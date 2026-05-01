"""Service grants — logique métier partage de wallets (LOT_04)."""
from __future__ import annotations

import base64
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.db.repositories import grants as grants_repo
from app.db.repositories import wallets as wallets_repo
from app.models.api.grants import (
    CreateGrantRequest,
    GrantCreateResponse,
    GrantItem,
    GrantListResponse,
    MyGrantResponse,
    UpdateGrantRequest,
)
from app.services.audit import audit_log_insert
from app.services.permissions import PERM_SHARE, has, is_subset, to_names

# ─── Helpers privés ───────────────────────────────────────────────────────────


def _decode_key(b64_value: str) -> bytes:
    try:
        return base64.b64decode(b64_value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_base64",
                "message": "encrypted_wallet_key_for_grantee is not valid base64",
            },
        ) from exc


async def _load_wallet_and_check_share(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
) -> tuple[UUID, int]:
    """Vérifie que le caller a un grant [share] sur le wallet.

    Retourne (owner_user_id, caller_permissions).
    Lève 404 si pas de grant, 403 si permissions insuffisantes.
    """
    wallet = await wallets_repo.get_wallet_for_user(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "wallet_not_found", "message": "Wallet not found"},
        )
    if not has(wallet.my_permissions, PERM_SHARE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "missing_share_permission",
                "message": "You need the [share] permission to manage grants on this wallet",
            },
        )
    return wallet.owner_user_id, wallet.my_permissions


# ─── List grants ──────────────────────────────────────────────────────────────


async def list_grants(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
) -> GrantListResponse:
    """Liste tous les grants du wallet. Requiert [share]."""
    owner_user_id, _ = await _load_wallet_and_check_share(
        conn, wallet_id=wallet_id, caller_user_id=caller_user_id
    )
    items: list[GrantItem] = await grants_repo.list_grants(
        conn, wallet_id=wallet_id, owner_user_id=owner_user_id
    )
    return GrantListResponse(grants=items)


# ─── My grant ─────────────────────────────────────────────────────────────────


async def get_my_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
) -> MyGrantResponse:
    """Retourne le grant du caller (avec encrypted_wallet_key). Lève 404 si absent."""
    # On doit d'abord vérifier l'existence du wallet + récupérer l'owner
    # sans exiger [share] — GET my-grant ne requiert aucune permission spéciale,
    # juste d'avoir un grant (ce qui prouve l'accès).
    wallet = await wallets_repo.get_wallet_for_user(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "wallet_not_found", "message": "Wallet not found"},
        )
    my_grant = await grants_repo.get_my_grant(
        conn,
        wallet_id=wallet_id,
        user_id=caller_user_id,
        owner_user_id=wallet.owner_user_id,
    )
    if my_grant is None:  # pragma: no cover — get_wallet_for_user garantit l'existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "grant_not_found", "message": "No grant found for this wallet"},
        )
    return my_grant


# ─── Create grant ─────────────────────────────────────────────────────────────


async def create_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    req: CreateGrantRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> GrantCreateResponse:
    """Crée un grant. Requiert [share] et subset-check des permissions."""
    _, caller_perms = await _load_wallet_and_check_share(
        conn, wallet_id=wallet_id, caller_user_id=caller_user_id
    )

    # Cannot share with self
    if req.grantee_user_id == caller_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "cannot_share_with_self",
                "message": "You cannot share a wallet with yourself",
            },
        )

    # Subset check : target_perms ⊆ caller_perms
    if not is_subset(req.permissions, caller_perms):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "permissions_exceed_caller",
                "message": (
                    "You cannot grant permissions you do not possess yourself. "
                    f"Requested: {to_names(req.permissions)}, "
                    f"You have: {to_names(caller_perms)}"
                ),
            },
        )

    # Grantee must exist
    grantee = await grants_repo.get_user_by_id(conn, req.grantee_user_id)
    if grantee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "grantee_not_found",
                "message": "Grantee user does not exist",
            },
        )

    enc_key = _decode_key(req.encrypted_wallet_key_for_grantee)

    try:
        async with conn.transaction():
            grant_id = await grants_repo.insert_grant(
                conn,
                wallet_id=wallet_id,
                grantee_user_id=req.grantee_user_id,
                encrypted_wallet_key=enc_key,
                permissions=req.permissions,
                granted_by_user_id=caller_user_id,
            )
            await audit_log_insert(
                conn,
                "wallet.grant_created",
                actor_user_id=caller_user_id,
                actor_ip=actor_ip,
                target_wallet_id=wallet_id,
                target_user_id=req.grantee_user_id,
                metadata={
                    "grant_id": str(grant_id),
                    "permissions": req.permissions,
                    "permissions_names": to_names(req.permissions),
                },
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "grant_already_exists",
                "message": "This user already has a grant on this wallet. Use PATCH to update it.",
            },
        ) from exc

    return GrantCreateResponse(grant_id=grant_id)


# ─── Update grant ─────────────────────────────────────────────────────────────


async def update_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    grant_id: UUID,
    req: UpdateGrantRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Met à jour les permissions d'un grant. Requiert [share] + subset-check."""
    owner_user_id, caller_perms = await _load_wallet_and_check_share(
        conn, wallet_id=wallet_id, caller_user_id=caller_user_id
    )

    # Charger le grant cible
    grant_row = await grants_repo.get_grant_by_id(conn, grant_id=grant_id, wallet_id=wallet_id)
    if grant_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "grant_not_found", "message": "Grant not found"},
        )

    # Applicative check avant que le trigger DB ne remonte une erreur technique
    if grant_row["grantee_user_id"] == owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_grant_immutable",
                "message": "The owner's grant cannot be modified",
            },
        )

    # Subset check
    if not is_subset(req.permissions, caller_perms):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "permissions_exceed_caller",
                "message": (
                    "You cannot grant permissions you do not possess yourself. "
                    f"Requested: {to_names(req.permissions)}, "
                    f"You have: {to_names(caller_perms)}"
                ),
            },
        )

    enc_key: bytes | None = None
    if req.encrypted_wallet_key_for_grantee is not None:
        enc_key = _decode_key(req.encrypted_wallet_key_for_grantee)

    async with conn.transaction():
        await grants_repo.update_grant(
            conn,
            grant_id=grant_id,
            permissions=req.permissions,
            encrypted_wallet_key=enc_key,
        )
        await audit_log_insert(
            conn,
            "wallet.grant_updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_user_id=grant_row["grantee_user_id"],
            metadata={
                "grant_id": str(grant_id),
                "permissions": req.permissions,
                "permissions_names": to_names(req.permissions),
            },
        )


# ─── Delete grant ─────────────────────────────────────────────────────────────


async def delete_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    grant_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Supprime un grant. Requiert [share]. Refuse de révoquer le grant owner."""
    owner_user_id, _ = await _load_wallet_and_check_share(
        conn, wallet_id=wallet_id, caller_user_id=caller_user_id
    )

    grant_row = await grants_repo.get_grant_by_id(conn, grant_id=grant_id, wallet_id=wallet_id)
    if grant_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "grant_not_found", "message": "Grant not found"},
        )

    # Applicative check : ne pas supprimer le grant owner
    if grant_row["grantee_user_id"] == owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_grant_immutable",
                "message": "The owner's grant cannot be revoked",
            },
        )

    grantee_user_id: UUID = grant_row["grantee_user_id"]

    async with conn.transaction():
        # LOT_08 : cascade — révoque les API keys de grantee_user_id sur ce wallet
        from app.core import api_key_cache as cache_mod
        from app.db.repositories import api_keys as api_keys_repo

        revoked_count = await api_keys_repo.revoke_api_keys_by_owner_on_wallet(
            conn,
            wallet_id=wallet_id,
            owner_user_id=grantee_user_id,
        )
        # Invalide le cache pour les clés révoquées (on ne connaît pas leurs IDs ici,
        # mais cache_invalidate par api_key_id nécessite les IDs individuels —
        # on vide tout le cache pour ce wallet owner, acceptable pour MVP).
        # Alternative : récupérer les IDs avant DELETE. Choix MVP : invalider globalement
        # les entrées de cache pour cet owner est trop coûteux sans les IDs.
        # La révocation DB suffit : le cache TTL 60s est un best-effort.
        # Pour une invalidation propre on vide le cache complet de validation.
        if revoked_count > 0:
            cache_mod.cache_clear_all()

        await grants_repo.delete_grant(conn, grant_id=grant_id)
        await audit_log_insert(
            conn,
            "wallet.grant_deleted",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_user_id=grantee_user_id,
            metadata={"grant_id": str(grant_id), "cascaded_api_keys_revoked": revoked_count},
        )
