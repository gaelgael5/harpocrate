"""Requêtes SQL pour la table wallet_grants — LOT_04."""
from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

import asyncpg

from app.models.api.grants import GrantItem, MyGrantResponse

# ─── Helpers de mapping ───────────────────────────────────────────────────────


def _row_to_grant_item(row: Any, owner_user_id: UUID) -> GrantItem:
    return GrantItem(
        id=row["id"],
        grantee_user_id=row["grantee_user_id"],
        grantee_email=row["email"],
        grantee_display_name=row["display_name"],
        permissions=row["permissions"],
        is_owner=row["grantee_user_id"] == owner_user_id,
        granted_by_user_id=row["granted_by_user_id"],
        granted_at=row["granted_at"],
    )


def _row_to_my_grant(row: Any, owner_user_id: UUID) -> MyGrantResponse:
    raw_key: bytes = bytes(row["encrypted_wallet_key"])
    return MyGrantResponse(
        id=row["id"],
        permissions=row["permissions"],
        encrypted_wallet_key=base64.b64encode(raw_key).decode(),
        is_owner=row["grantee_user_id"] == owner_user_id,
    )


# ─── SELECT liste complète ────────────────────────────────────────────────────


async def list_grants(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    owner_user_id: UUID,
) -> list[GrantItem]:
    """Retourne tous les grants d'un wallet, avec infos grantee jointes."""
    rows = await conn.fetch(
        """
        SELECT
            wg.id,
            wg.grantee_user_id,
            wg.permissions,
            wg.granted_by_user_id,
            wg.granted_at,
            u.email,
            u.display_name
        FROM wallet_grants wg
        JOIN users u ON u.id = wg.grantee_user_id
        WHERE wg.wallet_id = $1
        ORDER BY wg.granted_at ASC
        """,
        wallet_id,
    )
    return [_row_to_grant_item(r, owner_user_id) for r in rows]


# ─── SELECT grant unique par ID ───────────────────────────────────────────────


async def get_grant_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    grant_id: UUID,
    wallet_id: UUID,
) -> Any | None:
    """Retourne le grant si il appartient au wallet, None sinon."""
    return await conn.fetchrow(
        """
        SELECT id, wallet_id, grantee_user_id, permissions, granted_by_user_id, granted_at
        FROM wallet_grants
        WHERE id = $1 AND wallet_id = $2
        """,
        grant_id,
        wallet_id,
    )


# ─── SELECT my-grant ──────────────────────────────────────────────────────────


async def get_my_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    user_id: UUID,
    owner_user_id: UUID,
) -> MyGrantResponse | None:
    """Retourne le grant du caller (avec encrypted_wallet_key), None si absent."""
    row = await conn.fetchrow(
        """
        SELECT id, grantee_user_id, permissions, encrypted_wallet_key
        FROM wallet_grants
        WHERE wallet_id = $1 AND grantee_user_id = $2
        """,
        wallet_id,
        user_id,
    )
    if row is None:
        return None
    return _row_to_my_grant(row, owner_user_id)


# ─── INSERT grant ─────────────────────────────────────────────────────────────


async def insert_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    grantee_user_id: UUID,
    encrypted_wallet_key: bytes,
    permissions: int,
    granted_by_user_id: UUID,
) -> UUID:
    """Insère un nouveau grant. Lève UniqueViolationError si déjà existant."""
    result: UUID = await conn.fetchval(
        """
        INSERT INTO wallet_grants
            (wallet_id, grantee_user_id, encrypted_wallet_key, permissions, granted_by_user_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        wallet_id,
        grantee_user_id,
        encrypted_wallet_key,
        permissions,
        granted_by_user_id,
    )
    return result


# ─── UPDATE grant ─────────────────────────────────────────────────────────────


async def update_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    grant_id: UUID,
    permissions: int,
    encrypted_wallet_key: bytes | None,
) -> None:
    """Met à jour permissions (et optionnellement la clé chiffrée) d'un grant."""
    if encrypted_wallet_key is not None:
        await conn.execute(
            """
            UPDATE wallet_grants
            SET permissions = $2, encrypted_wallet_key = $3
            WHERE id = $1
            """,
            grant_id,
            permissions,
            encrypted_wallet_key,
        )
    else:
        await conn.execute(
            "UPDATE wallet_grants SET permissions = $2 WHERE id = $1",
            grant_id,
            permissions,
        )


# ─── DELETE grant ─────────────────────────────────────────────────────────────


async def delete_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    grant_id: UUID,
) -> None:
    """Supprime un grant par son ID."""
    await conn.execute(
        "DELETE FROM wallet_grants WHERE id = $1",
        grant_id,
    )


# ─── Lookup utilisateur par ID ────────────────────────────────────────────────


async def get_user_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    user_id: UUID,
) -> dict[str, Any] | None:
    """Retourne id, email, display_name pour le user_id donné."""
    row = await conn.fetchrow(
        "SELECT id, email, display_name FROM users WHERE id = $1",
        user_id,
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
    }
