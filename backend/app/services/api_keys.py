"""Service api_keys — logique métier CRUD API keys (LOT_08)."""
from __future__ import annotations

import base64
import datetime
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core import api_key_cache as cache_mod
from app.core.api_key_token import encode_token
from app.core.config import settings
from app.db.repositories import api_keys as api_keys_repo
from app.db.repositories import wallets as wallets_repo
from app.models.api.api_keys import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyItem,
    ApiKeyListResponse,
    ApiKeyPatchRequest,
)
from app.services.audit import audit_log_insert
from app.services.permissions import PERM_SHARE, has, is_subset, to_names

# ─── Helpers privés ───────────────────────────────────────────────────────────


async def _require_share_permission(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
) -> int:
    """Vérifie que le caller a [share] sur le wallet. Retourne my_permissions."""
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
                "message": "You need the [share] permission to manage API keys on this wallet",
            },
        )
    return wallet.my_permissions


def _decode_b64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": f"{field} is not valid base64"},
        ) from exc


# ─── List ─────────────────────────────────────────────────────────────────────


async def list_api_keys(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
) -> ApiKeyListResponse:
    """Liste les API keys du wallet. Requiert [share]."""
    await _require_share_permission(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)
    items: list[ApiKeyItem] = await api_keys_repo.list_api_keys_for_wallet(
        conn, wallet_id=wallet_id
    )
    return ApiKeyListResponse(api_keys=items)


# ─── Create ───────────────────────────────────────────────────────────────────


async def create_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    req: ApiKeyCreateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> ApiKeyCreateResponse:
    """Crée une API key et retourne le token complet (one-shot). Requiert [share]."""
    caller_perms = await _require_share_permission(
        conn, wallet_id=wallet_id, caller_user_id=caller_user_id
    )

    # Subset check : les permissions de la clé ⊆ celles du caller
    if not is_subset(req.permissions, caller_perms):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "permissions_exceed_caller",
                "message": (
                    "API key permissions must be a subset of your own permissions. "
                    f"Requested: {to_names(req.permissions)}, "
                    f"You have: {to_names(caller_perms)}"
                ),
            },
        )

    # Décode les blobs
    auth_hash_bytes = _decode_b64(req.auth_hash, "auth_hash")
    auth_salt_bytes = _decode_b64(req.auth_salt, "auth_salt")
    enc_wallet_key_bytes = _decode_b64(req.encrypted_wallet_key, "encrypted_wallet_key")
    enc_dkey_bytes = _decode_b64(
        req.encrypted_decryption_key_for_owner, "encrypted_decryption_key_for_owner"
    )

    # Calcul de exp (0 = pas d'expiration)
    if req.expires_at is None:
        exp = 0
    else:
        # Normalise en UTC
        expires_utc = req.expires_at.astimezone(datetime.UTC)
        exp = int(expires_utc.timestamp())

    async with conn.transaction():
        api_key_id = await api_keys_repo.insert_api_key(
            conn,
            wallet_id=wallet_id,
            owner_user_id=caller_user_id,
            name=req.name,
            description=req.description,
            auth_hash=auth_hash_bytes,
            auth_salt=auth_salt_bytes,
            auth_kdf_memory_kb=req.auth_kdf_memory_kb,
            auth_kdf_iterations=req.auth_kdf_iterations,
            auth_kdf_parallelism=req.auth_kdf_parallelism,
            encrypted_wallet_key=enc_wallet_key_bytes,
            encrypted_decryption_key_for_owner=enc_dkey_bytes,
            permissions=req.permissions,
            expires_at=req.expires_at,
        )

        await audit_log_insert(
            conn,
            "api_key.created",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_api_key_id=api_key_id,
            metadata={
                "api_key_id": str(api_key_id),
                "name": req.name,
                "permissions": req.permissions,
                "permissions_names": to_names(req.permissions),
            },
        )

    # Assemble le token — auth_secret et decryption_key ne sont pas stockés en DB
    token = encode_token(
        api_key_id=api_key_id,
        exp=exp,
        perms=req.permissions,
        auth_secret_b64=req.auth_secret,
        dkey_b64=req.decryption_key,
        master_key_b64=settings.hmac_key,
    )

    return ApiKeyCreateResponse(api_key_id=api_key_id, token=token)


# ─── Update ───────────────────────────────────────────────────────────────────


async def update_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    api_key_id: UUID,
    req: ApiKeyPatchRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Met à jour name/description d'une API key. Requiert [share]."""
    await _require_share_permission(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    # Vérifie que la clé existe sur ce wallet
    existing = await api_keys_repo.get_api_key_by_id(
        conn, api_key_id=api_key_id, wallet_id=wallet_id
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "api_key_not_found", "message": "API key not found"},
        )

    found = await api_keys_repo.update_api_key_metadata(
        conn,
        api_key_id=api_key_id,
        wallet_id=wallet_id,
        name=req.name,
        description=req.description,
    )
    if not found:  # pragma: no cover — vérifié avant
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "api_key_not_found", "message": "API key not found"},
        )

    await audit_log_insert(
        conn,
        "api_key.updated",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        target_api_key_id=api_key_id,
        metadata={
            "api_key_id": str(api_key_id),
            "updated_fields": [
                f for f, v in [("name", req.name), ("description", req.description)]
                if v is not None
            ],
        },
    )


# ─── Revoke ───────────────────────────────────────────────────────────────────


async def revoke_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    api_key_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Révoque une API key (soft delete). Requiert [share]."""
    await _require_share_permission(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    async with conn.transaction():
        found = await api_keys_repo.revoke_api_key(
            conn, api_key_id=api_key_id, wallet_id=wallet_id
        )
        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "api_key_not_found",
                    "message": "API key not found or already revoked",
                },
            )

        # Invalide le cache immédiatement
        cache_mod.cache_invalidate(api_key_id)

        await audit_log_insert(
            conn,
            "api_key.revoked",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_api_key_id=api_key_id,
            metadata={"api_key_id": str(api_key_id)},
        )
