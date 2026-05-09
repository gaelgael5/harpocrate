"""Service wallets — logique métier CRUD wallets + transfer ownership."""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import wallet_environments as wallet_env_repo
from app.db.repositories import wallets as wallets_repo
from app.models.api.exports import (
    ExportedSecret,
    ExportedWallet,
    WalletExport,
    WalletImportRequest,
    WalletImportResponse,
)
from app.models.api.generators import GenerationDescriptor
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


async def _validate_environment_ownership(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    environment_id: UUID | None,
    owner_user_id: UUID,
) -> None:
    """Vérifie que l'environment_id (s'il est fourni) appartient bien à
    `owner_user_id`. Sinon lève 400 environment_not_owned (ne pas leak via
    404 — ça permettrait de tester l'existence d'un id côté autres users).
    """
    if environment_id is None:
        return
    env = await wallet_env_repo.get_by_id(conn, environment_id)
    if env is None or env.owner_user_id != owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "environment_not_owned",
                "message": "environment_id does not exist or is not owned by you",
            },
        )


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

    # LOT_58 : valide que l'environment_id (s'il est fourni) appartient
    # bien au caller — sinon on permettrait à un user de ranger un wallet
    # dans l'env d'un autre user (leak d'identifiants d'env).
    await _validate_environment_ownership(
        conn, environment_id=req.environment_id, owner_user_id=caller_user_id
    )

    async with conn.transaction():
        wallet_id = await wallets_repo.insert_wallet_with_grant(
            conn,
            name=req.name,
            description=req.description,
            owner_user_id=caller_user_id,
            tags=req.tags,
            encrypted_wallet_key=enc_key,
            environment_id=req.environment_id,
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
) -> tuple[list[WalletWithGrant], str | None, list[WalletWithGrant]]:
    """Retourne (wallets_actifs, next_cursor, wallets_supprimés)."""
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

    deleted_wallets = await wallets_repo.list_deleted_wallets_for_user(
        conn, user_id=caller_user_id
    )

    return wallets, next_cursor, deleted_wallets


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

    # LOT_58 : si le caller veut changer l'env, on valide d'abord que le
    # nouvel env (s'il n'est pas NULL) lui appartient.
    if req.set_environment:
        await _validate_environment_ownership(
            conn,
            environment_id=req.environment_id,
            owner_user_id=wallet.owner_user_id,
        )

    async with conn.transaction():
        from app.db.repositories.wallets import _ENV_UNCHANGED

        await wallets_repo.update_wallet(
            conn,
            wallet_id=wallet_id,
            name=req.name,
            description=req.description,
            tags=req.tags,
            environment_id=(
                req.environment_id if req.set_environment else _ENV_UNCHANGED
            ),
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
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Suppression logique. Requiert owner. Purge physique 24h après."""
    wallet = await get_wallet(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    if wallet.owner_user_id != caller_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "not_owner", "message": "Only the wallet owner can delete it"},
        )

    if wallet.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_deleted", "message": "Wallet is already pending deletion"},
        )

    async with conn.transaction():
        await wallets_repo.soft_delete_wallet(conn, wallet_id)
        await audit_log_insert(
            conn,
            "wallet.soft_deleted",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            metadata={"wallet_name": wallet.name},
        )


async def restore_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Annule la suppression logique. Requiert owner."""
    wallet = await get_wallet(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    if wallet.owner_user_id != caller_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "not_owner", "message": "Only the wallet owner can restore it"},
        )

    if wallet.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_deleted", "message": "Wallet is not pending deletion"},
        )

    async with conn.transaction():
        await wallets_repo.restore_wallet(conn, wallet_id)
        await audit_log_insert(
            conn,
            "wallet.restored",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            metadata={"wallet_name": wallet.name},
        )


async def purge_expired_wallets(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Purge physique des wallets dont la fenêtre de 24h est expirée."""
    deleted_ids = await wallets_repo.purge_expired_wallets(conn)
    for wallet_id in deleted_ids:
        logger.info("wallet.purged", wallet_id=str(wallet_id))


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


# ─── Export structure ─────────────────────────────────────────────────────────

_READ_BIT = 0x01


async def export_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> WalletExport:
    """Exporte la structure du wallet (sans valeurs). Requiert permission [read]."""
    wallet = await get_wallet(conn, wallet_id=wallet_id, caller_user_id=caller_user_id)

    if not (wallet.my_permissions & _READ_BIT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "Permission [read] required to export this wallet",
            },
        )

    data = await wallets_repo.export_wallet_data(conn, wallet_id=wallet_id)

    secrets_exported: list[ExportedSecret] = []
    for s in data.get("secrets", []):
        descriptor: GenerationDescriptor | None = None
        if s["generation_descriptor"] is not None:
            descriptor = _parse_descriptor(s["generation_descriptor"])
        secrets_exported.append(
            ExportedSecret(
                name=s["name"],
                description=s["description"],
                tags=s["tags"],
                is_placeholder=s["is_placeholder"],
                generation_descriptor=descriptor,
                generation_version=s["generation_version"],
                linked_secret_name=s["linked_secret_name"],
            )
        )

    wallet_info = data["wallet"]
    export = WalletExport(
        format_version="1",
        exported_at=datetime.now(tz=UTC),
        exported_from=settings.public_url,
        wallet=ExportedWallet(
            name=wallet_info["name"],
            description=wallet_info["description"],
            tags=wallet_info["tags"],
        ),
        secrets=secrets_exported,
    )

    await audit_log_insert(
        conn,
        "wallet.exported_structure",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        metadata={"secret_count": len(secrets_exported)},
    )

    return export


def _parse_descriptor(raw: dict[str, Any]) -> GenerationDescriptor | None:
    """Reconstruit un GenerationDescriptor à partir du dict JSONB stocké."""
    try:
        from pydantic import TypeAdapter

        adapter: TypeAdapter[GenerationDescriptor] = TypeAdapter(GenerationDescriptor)
        return adapter.validate_python(raw)
    except Exception:
        return None


# ─── Import structure ─────────────────────────────────────────────────────────


async def import_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    req: WalletImportRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> WalletImportResponse:
    """Importe un wallet depuis une structure exportée. Atomique."""
    enc_key = _decode_key(req.encrypted_wallet_key_for_owner)

    secrets_dicts: list[dict[str, Any]] = []
    for s in req.secrets:
        descriptor_dict: dict[str, Any] | None = None
        if s.generation_descriptor is not None:
            descriptor_dict = s.generation_descriptor.model_dump()
        secrets_dicts.append(
            {
                "name": s.name,
                "description": s.description,
                "tags": [t.strip().lower() for t in s.tags if t.strip()],
                "is_placeholder": s.is_placeholder,
                "generation_descriptor": descriptor_dict,
                "generation_version": s.generation_version,
                "linked_secret_name": s.linked_secret_name,
            }
        )

    wallet_tags = [t.strip().lower() for t in req.wallet.tags if t.strip()]

    wallet_id, secrets_created = await wallets_repo.import_wallet_atomic(
        conn,
        wallet_name=req.wallet.name,
        wallet_description=req.wallet.description,
        wallet_tags=wallet_tags,
        encrypted_wallet_key=enc_key,
        owner_user_id=caller_user_id,
        secrets=secrets_dicts,
    )

    await audit_log_insert(
        conn,
        "wallet.imported",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        metadata={
            "source_wallet_name": req.wallet.name,
            "secret_count": secrets_created,
        },
    )

    return WalletImportResponse(
        wallet_id=str(wallet_id),
        secrets_created=secrets_created,
        skipped=[],
    )
