"""Repository — table remote_backup_connection (LOT remote backups).

Aucune logique de chiffrement ici : on stocke et on lit le blob `credentials_encrypted`
tel quel. Le chiffrement/déchiffrement est fait par la couche service.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg


async def list_active(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[asyncpg.Record]:
    """Liste toutes les connexions actives (non soft-deleted), triées par création décroissante."""
    return await conn.fetch(
        """
        SELECT id, name, kind, config, credentials_encrypted,
               created_at, updated_at, created_by_user_id, deleted_at
        FROM remote_backup_connection
        WHERE deleted_at IS NULL
        ORDER BY created_at DESC
        """
    )


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    connection_id: UUID,
) -> asyncpg.Record | None:
    """Retourne la connexion (active OU soft-deleted) ou None si inexistante."""
    return await conn.fetchrow(
        """
        SELECT id, name, kind, config, credentials_encrypted,
               created_at, updated_at, created_by_user_id, deleted_at
        FROM remote_backup_connection
        WHERE id = $1
        """,
        connection_id,
    )


async def insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    name: str,
    kind: str,
    config: dict[str, Any],
    credentials_encrypted: bytes,
    created_by_user_id: UUID | None,
) -> UUID:
    """Insère une nouvelle connexion. Lève UniqueViolationError si name dupliqué (parmi actives)."""
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO remote_backup_connection
            (name, kind, config, credentials_encrypted, created_by_user_id)
        VALUES ($1, $2, $3::jsonb, $4, $5)
        RETURNING id
        """,
        name,
        kind,
        json.dumps(config),
        credentials_encrypted,
        created_by_user_id,
    )
    return new_id


async def update(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    connection_id: UUID,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    credentials_encrypted: bytes | None = None,
) -> int:
    """Update partiel. Champs `None` ne sont pas modifiés. Retourne le nombre de rows affectées."""
    sets: list[str] = []
    params: list[object] = []
    if name is not None:
        params.append(name)
        sets.append(f"name = ${len(params)}")
    if config is not None:
        params.append(json.dumps(config))
        sets.append(f"config = ${len(params)}::jsonb")
    if credentials_encrypted is not None:
        params.append(credentials_encrypted)
        sets.append(f"credentials_encrypted = ${len(params)}")

    if not sets:
        return 0  # rien à mettre à jour

    params.append(connection_id)
    query = (
        f"UPDATE remote_backup_connection SET {', '.join(sets)} "
        f"WHERE id = ${len(params)} AND deleted_at IS NULL"
    )
    result = await conn.execute(query, *params)
    # asyncpg retourne "UPDATE n" sous forme de string
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def soft_delete(
    conn: asyncpg.Connection[asyncpg.Record],
    connection_id: UUID,
) -> int:
    """Soft-delete (deleted_at = NOW). Retourne le nombre de rows affectées."""
    result = await conn.execute(
        """
        UPDATE remote_backup_connection
        SET deleted_at = NOW()
        WHERE id = $1 AND deleted_at IS NULL
        """,
        connection_id,
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
