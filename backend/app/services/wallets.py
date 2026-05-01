"""Service wallets — logique métier CRUD wallets + transfer ownership."""
from __future__ import annotations

import base64
from collections import defaultdict
from time import monotonic
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.db.repositories import wallets as wallets_repo
from app.models.api.wallets import (
    WalletCreateRequest,
    WalletPatchRequest,
)
from app.models.db.wallet import WalletWithGrant
from app.services.audit import audit_log_insert

# ─── Rate limiting in-memory (lookup) ────────────────────────────────────────

_lookup_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 30
_RATE_WINDOW = 60.0


async def rate_limit_lookup(ip: str) -> None:
    """Lève 429 si l'IP dépasse 30 requêtes par minute."""
    now = monotonic()
    attempts = _lookup_attempts[ip]
    _lookup_attempts[ip] = [t for t in attempts if now - t < _RATE_WINDOW]
    if len(_lookup_attempts[ip]) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limit_exceeded", "message": "Too many lookup requests"},
        )
    _lookup_attempts[ip].append(now)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _decode_key(b64_value: str) -> bytes:
    try:
        return base64.b64decode(b64_value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_base64",
                "message": "encrypted_wallet_key_for_owner is not valid base64",
            },
        ) from exc


# ─── Create ───────────────────────────────────────────────────────────────────


async def create_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    req: WalletCreateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> UUID:
    """Crée un wallet avec grant owner (permissions=63). Retourne wallet_id."""
    enc_key = _decode_key(req.encrypted_wallet_key_for_owner)

    async with conn.transaction():
        wallet_id = await wallets_repo.insert_wallet_with_grant(
            conn,
            name=req.name,
            description=req.description,
            owner_user_id=caller_user_id,
            tags=req.tags,
            encrypted_wallet_key=enc_key,
        )
        await audit_log_insert(
            conn,
            "wallet.created",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            metadata={"wallet_name": req.name},
        )

    return wallet_id


# ─── List ─────────────────────────────────────────────────────────────────────


async def list_wallets(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    caller_user_id: UUID,
    limit: int,
    cursor: str | None,
    tag_filter: str | None,
    name_contains: str | None,
) -> tuple[list[WalletWithGrant], str | None]:
    """Retourne (wallets, next_cursor). next_cursor vaut None si page finale."""
    cursor_updated_at = None
    cursor_id = None

    if cursor:
        try:
            cursor_updated_at, cursor_id = wallets_repo.decode_cursor(cursor)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_cursor", "message": "Cursor is malformed"},
            ) from exc

    # Fetch limit+1 pour détecter s'il y a une page suivante
    wallets = await wallets_repo.list_wallets_for_user(
        conn,
        user_id=caller_user_id,
        limit=limit + 1,
        cursor_updated_at=cursor_updated_at,
        cursor_id=cursor_id,
        tag_filter=tag_filter,
        name_contains=name_contains,
    )

    next_cursor: str | None = None
    if len(wallets) > limit:
        wallets = wallets[:limit]
        last = wallets[-1]
        next_cursor = wallets_repo.encode_cursor(last.updated_at, last.id)

    return wallets, next_cursor


# ─── Get ──────────────────────────────────────────────────────────────────────


async def get_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
) -> WalletWithGrant:
    """Retourne le wallet ou lève 404 (pas 403, pour ne pas révéler l'existence)."""
    wallet = await wallets_repo.get_wallet_for_user(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "wallet_not_found", "message": "Wallet not found"},
        )
    return wallet


# ─── Patch ────────────────────────────────────────────────────────────────────

# Permission bit : share = bit 5 (0x20) dans le schéma.
# La spec dit "owner ou share" pour le PATCH. On utilise le bit share (0x20 = 32).
_SHARE_BIT = 0x20


async def patch_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    req: WalletPatchRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> WalletWithGrant:
    """Met à jour partiellement name/description/tags. Requiert owner ou share."""
    wallet = await get_wallet(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    is_owner = wallet.owner_user_id == caller_user_id
    has_share = bool(wallet.my_permissions & _SHARE_BIT)

    if not is_owner and not has_share:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "You need owner or share permission to update this wallet",
            },
        )

    async with conn.transaction():
        await wallets_repo.update_wallet(
            conn,
            wallet_id=wallet_id,
            name=req.name,
            description=req.description,
            tags=req.tags,
        )
        await audit_log_insert(
            conn,
            "wallet.updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            metadata={"wallet_name": wallet.name},
        )

    updated = await wallets_repo.get_wallet_for_user(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if updated is None:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return updated


# ─── Delete ───────────────────────────────────────────────────────────────────


async def delete_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    confirmation: str,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Hard-delete du wallet. Requiert owner + confirmation par nom exact."""
    wallet = await get_wallet(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    if wallet.owner_user_id != caller_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "not_owner", "message": "Only the wallet owner can delete it"},
        )

    if confirmation != wallet.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "confirmation_mismatch",
                "message": "Confirmation does not match the wallet name exactly",
            },
        )

    async with conn.transaction():
        await wallets_repo.delete_wallet(conn, wallet_id)
        await audit_log_insert(
            conn,
            "wallet.deleted",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            metadata={"wallet_name": wallet.name},
        )


# ─── Transfer ownership ───────────────────────────────────────────────────────


async def transfer_ownership(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    new_owner_user_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> WalletWithGrant:
    """Transfert de l'ownership. Requiert owner. Le new owner doit avoir un grant."""
    wallet = await get_wallet(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    if wallet.owner_user_id != caller_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "not_owner",
                "message": "Only the wallet owner can transfer ownership",
            },
        )

    has_grant = await wallets_repo.grant_exists(
        conn, wallet_id=wallet_id, user_id=new_owner_user_id
    )
    if not has_grant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "new_owner_has_no_grant",
                "message": "The new owner must already have a grant on this wallet",
            },
        )

    async with conn.transaction():
        await wallets_repo.transfer_ownership(
            conn,
            wallet_id=wallet_id,
            new_owner_user_id=new_owner_user_id,
        )
        await audit_log_insert(
            conn,
            "wallet.ownership_transferred",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            metadata={
                "wallet_name": wallet.name,
                "previous_owner_user_id": str(caller_user_id),
                "new_owner_user_id": str(new_owner_user_id),
            },
        )

    updated = await wallets_repo.get_wallet_for_user(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if updated is None:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return updated
