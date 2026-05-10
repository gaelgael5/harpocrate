"""Repository — table replication_nodes (LOT réplication itération 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import asyncpg


_SELECT_FIELDS = """
    id, strategy_id, label, host, port, replication_user, application_name,
    role, notes, last_seen_at, last_state, last_lag_bytes,
    created_at, updated_at, created_by_user_id
"""


async def list_for_strategy(
    conn: asyncpg.Connection[asyncpg.Record],
    strategy_id: UUID,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        SELECT {_SELECT_FIELDS}
        FROM replication_nodes
        WHERE strategy_id = $1
        ORDER BY LOWER(label) ASC
        """,
        strategy_id,
    )


async def list_all(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"SELECT {_SELECT_FIELDS} FROM replication_nodes ORDER BY LOWER(label) ASC"
    )


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    node_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_SELECT_FIELDS} FROM replication_nodes WHERE id = $1",
        node_id,
    )


async def get_by_application_name(
    conn: asyncpg.Connection[asyncpg.Record],
    application_name: str,
) -> asyncpg.Record | None:
    """Lookup utilisé par `refresh_nodes_state` pour matcher les rows
    `pg_stat_replication.application_name` aux nodes en DB."""
    return await conn.fetchrow(
        f"""
        SELECT {_SELECT_FIELDS}
        FROM replication_nodes
        WHERE LOWER(application_name) = LOWER($1)
        """,
        application_name,
    )


async def insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    strategy_id: UUID,
    label: str,
    host: str,
    port: int,
    replication_user: str,
    application_name: str,
    role: str,
    notes: str | None,
    created_by_user_id: UUID | None,
) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO replication_nodes (
            strategy_id, label, host, port, replication_user,
            application_name, role, notes, created_by_user_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        strategy_id,
        label,
        host,
        port,
        replication_user,
        application_name,
        role,
        notes,
        created_by_user_id,
    )


async def delete(
    conn: asyncpg.Connection[asyncpg.Record],
    node_id: UUID,
) -> int:
    result = await conn.execute(
        "DELETE FROM replication_nodes WHERE id = $1", node_id
    )
    try:
        return int(result.split(" ")[1])
    except (IndexError, ValueError):
        return 0


async def update_observed_state(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    node_id: UUID,
    last_seen_at: datetime,
    last_state: Literal["streaming", "catchup", "disconnected", "unknown"],
    last_lag_bytes: int | None,
) -> int:
    result = await conn.execute(
        """
        UPDATE replication_nodes
        SET last_seen_at = $1, last_state = $2, last_lag_bytes = $3
        WHERE id = $4
        """,
        last_seen_at,
        last_state,
        last_lag_bytes,
        node_id,
    )
    try:
        return int(result.split(" ")[1])
    except (IndexError, ValueError):
        return 0
