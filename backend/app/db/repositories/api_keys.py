"""Requêtes SQL pour la table api_keys — LOT_08."""
from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.api.api_keys import ApiKeyItem
from app.models.db.api_key import ApiKeyRow

# ─── Mapping helpers ──────────────────────────────────────────────────────────


def _row_to_api_key_row(row: Any) -> ApiKeyRow:
    return ApiKeyRow(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        wallet_id=row["wallet_id"],
        owner_user_id=row["owner_user_id"],
        auth_hash=bytes(row["auth_hash"]),
        auth_salt=bytes(row["auth_salt"]),
        auth_kdf_memory_kb=row["auth_kdf_memory_kb"],
        auth_kdf_iterations=row["auth_kdf_iterations"],
        auth_kdf_parallelism=row["auth_kdf_parallelism"],
        encrypted_wallet_key=bytes(row["encrypted_wallet_key"]),
        encrypted_decryption_key_for_owner=bytes(row["encrypted_decryption_key_for_owner"]),
        permissions=row["permissions"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
    )


def _row_to_api_key_item(row: Any) -> ApiKeyItem:
    return ApiKeyItem(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        owner_user_id=row["owner_user_id"],
        permissions=row["permissions"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
    )


# ─── INSERT ───────────────────────────────────────────────────────────────────


async def insert_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    owner_user_id: UUID,
    name: str,
    description: str | None,
    auth_hash: bytes,
    auth_salt: bytes,
    auth_kdf_memory_kb: int,
    auth_kdf_iterations: int,
    auth_kdf_parallelism: int,
    encrypted_wallet_key: bytes,
    encrypted_decryption_key_for_owner: bytes,
    permissions: int,
    expires_at: datetime.datetime | None,
) -> UUID:
    """Insère une nouvelle API key. Retourne son UUID."""
    result: UUID = await conn.fetchval(
        """
        INSERT INTO api_keys (
            wallet_id, owner_user_id, name, description,
            auth_hash, auth_salt,
            auth_kdf_memory_kb, auth_kdf_iterations, auth_kdf_parallelism,
            encrypted_wallet_key, encrypted_decryption_key_for_owner,
            permissions, expires_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id
        """,
        wallet_id,
        owner_user_id,
        name,
        description,
        auth_hash,
        auth_salt,
        auth_kdf_memory_kb,
        auth_kdf_iterations,
        auth_kdf_parallelism,
        encrypted_wallet_key,
        encrypted_decryption_key_for_owner,
        permissions,
        expires_at,
    )
    return result


# ─── SELECT ───────────────────────────────────────────────────────────────────


async def list_api_keys_for_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
) -> list[ApiKeyItem]:
    """Retourne toutes les API keys d'un wallet (métadonnées uniquement)."""
    rows = await conn.fetch(
        """
        SELECT id, name, description, owner_user_id, permissions,
               expires_at, revoked_at, last_used_at, created_at
        FROM api_keys
        WHERE wallet_id = $1
        ORDER BY created_at ASC
        """,
        wallet_id,
    )
    return [_row_to_api_key_item(r) for r in rows]


async def get_api_key_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    api_key_id: UUID,
    wallet_id: UUID,
) -> ApiKeyRow | None:
    """Retourne une API key par son ID et wallet_id, None si absente."""
    row = await conn.fetchrow(
        """
        SELECT id, name, description, wallet_id, owner_user_id,
               auth_hash, auth_salt, auth_kdf_memory_kb, auth_kdf_iterations, auth_kdf_parallelism,
               encrypted_wallet_key, encrypted_decryption_key_for_owner,
               permissions, expires_at, revoked_at, last_used_at, created_at
        FROM api_keys
        WHERE id = $1 AND wallet_id = $2
        """,
        api_key_id,
        wallet_id,
    )
    if row is None:
        return None
    return _row_to_api_key_row(row)


# ─── UPDATE ───────────────────────────────────────────────────────────────────


async def update_api_key_metadata(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    api_key_id: UUID,
    wallet_id: UUID,
    name: str | None,
    description: str | None,
) -> bool:
    """Met à jour les métadonnées (name/description). Retourne True si trouvé."""
    if name is None and description is None:
        return True  # Rien à faire

    if name is not None and description is not None:
        result = await conn.execute(
            """
            UPDATE api_keys SET name = $3, description = $4
            WHERE id = $1 AND wallet_id = $2
            """,
            api_key_id,
            wallet_id,
            name,
            description,
        )
    elif name is not None:
        result = await conn.execute(
            "UPDATE api_keys SET name = $3 WHERE id = $1 AND wallet_id = $2",
            api_key_id,
            wallet_id,
            name,
        )
    else:
        result = await conn.execute(
            "UPDATE api_keys SET description = $3 WHERE id = $1 AND wallet_id = $2",
            api_key_id,
            wallet_id,
            description,
        )
    return str(result) != "UPDATE 0"


async def revoke_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    api_key_id: UUID,
    wallet_id: UUID,
) -> bool:
    """Pose revoked_at = NOW() sur l'API key. Retourne True si trouvé."""
    result = await conn.execute(
        """
        UPDATE api_keys SET revoked_at = NOW()
        WHERE id = $1 AND wallet_id = $2 AND revoked_at IS NULL
        """,
        api_key_id,
        wallet_id,
    )
    return str(result) != "UPDATE 0"


async def revoke_api_keys_by_owner_on_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    owner_user_id: UUID,
) -> int:
    """Révoque (soft delete) toutes les API keys de owner_user_id sur wallet_id.

    Appelé lors de la suppression du grant de l'owner (cascade LOT_08).
    Retourne le nombre de clés révoquées.
    """
    result = await conn.execute(
        """
        UPDATE api_keys SET revoked_at = NOW()
        WHERE wallet_id = $1 AND owner_user_id = $2 AND revoked_at IS NULL
        """,
        wallet_id,
        owner_user_id,
    )
    # result est du type "UPDATE N" (ex: "UPDATE 2") — peut être None en tests
    if not result or not isinstance(result, str):
        return 0
    parts = result.split()
    return int(parts[1]) if len(parts) >= 2 else 0
