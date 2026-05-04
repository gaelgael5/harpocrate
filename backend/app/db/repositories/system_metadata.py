"""Repository pour la table system_metadata — LOT_12A."""
from __future__ import annotations

import json
from typing import Any

import asyncpg


async def get_value(conn: asyncpg.Connection, key: str) -> Any:
    """Retourne la valeur JSON associée à la clé, ou None si absente."""
    row = await conn.fetchrow(
        "SELECT value FROM system_metadata WHERE key = $1", key
    )
    if row is None:
        return None
    return row["value"]


async def set_value(conn: asyncpg.Connection, key: str, value: Any) -> None:
    """Upsert la valeur JSON associée à la clé."""
    await conn.execute(
        """
        INSERT INTO system_metadata (key, value, updated_at)
        VALUES ($1, $2::jsonb, NOW())
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = NOW()
        """,
        key,
        json.dumps(value),
    )
