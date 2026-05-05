"""Repository — table replication_strategies (LOT_20)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg


async def list_strategies(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[asyncpg.Record]:
    """Liste toutes les stratégies (active en premier, puis ordre alphabétique)."""
    return await conn.fetch(
        """
        SELECT id, type, label, description, config, enabled, is_active,
               created_at, updated_at, created_by_user_id
        FROM replication_strategies
        ORDER BY is_active DESC, label ASC
        """
    )


async def get_active_strategy(
    conn: asyncpg.Connection[asyncpg.Record],
) -> asyncpg.Record | None:
    """Retourne la stratégie active (au plus une, garantie par index unique)."""
    return await conn.fetchrow(
        """
        SELECT id, type, label, description, config, enabled, is_active,
               created_at, updated_at, created_by_user_id
        FROM replication_strategies
        WHERE is_active = TRUE
        LIMIT 1
        """
    )


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    strategy_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, type, label, description, config, enabled, is_active,
               created_at, updated_at, created_by_user_id
        FROM replication_strategies
        WHERE id = $1
        """,
        strategy_id,
    )


async def upsert_strategy(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    type_: str,
    label: str,
    description: str | None,
    config: dict[str, Any],
    enabled: bool = True,
) -> UUID:
    """Insère une stratégie si label inconnu, sinon met à jour la config."""
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO replication_strategies (type, label, description, config, enabled)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        type_,
        label,
        description,
        json.dumps(config),
        enabled,
    )
    if new_id is None:
        new_id = await conn.fetchval(
            "SELECT id FROM replication_strategies WHERE label = $1",
            label,
        )
    return new_id


async def activate_strategy(
    conn: asyncpg.Connection[asyncpg.Record],
    strategy_id: UUID,
) -> bool:
    """Active une stratégie (et désactive toutes les autres) atomiquement."""
    async with conn.transaction():
        existing = await conn.fetchval(
            "SELECT 1 FROM replication_strategies WHERE id = $1 AND enabled = TRUE",
            strategy_id,
        )
        if existing is None:
            return False
        await conn.execute(
            "UPDATE replication_strategies SET is_active = FALSE WHERE is_active = TRUE"
        )
        await conn.execute(
            "UPDATE replication_strategies SET is_active = TRUE WHERE id = $1",
            strategy_id,
        )
    return True
