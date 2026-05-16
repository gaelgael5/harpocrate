"""Repository — table oauth_pending_session (LOT gdrive).

État éphémère d'un flux OAuth (gdrive aujourd'hui, extensible). TTL strict.
Aucune logique de chiffrement : payload et result sont des JSONB nus, le secret
est protégé par le fait que la ligne est supprimée dès la finalisation.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg


async def insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    provider: str,
    payload: dict[str, Any],
    target_connection_id: UUID | None,
    created_by_user_id: UUID | None,
    ttl_seconds: int,
) -> UUID:
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO oauth_pending_session
            (state, provider, payload, target_connection_id, created_by_user_id,
             expires_at)
        VALUES ($1, $2, $3::jsonb, $4, $5,
                NOW() + make_interval(secs => $6))
        RETURNING id
        """,
        state,
        provider,
        json.dumps(payload),
        target_connection_id,
        created_by_user_id,
        ttl_seconds,
    )
    return new_id


async def get_by_state(
    conn: asyncpg.Connection[asyncpg.Record], state: str
) -> asyncpg.Record | None:
    """Lit la ligne sans filtrer sur expires_at (debug / audit)."""
    return await conn.fetchrow("SELECT * FROM oauth_pending_session WHERE state = $1", state)


async def get_active_by_state(
    conn: asyncpg.Connection[asyncpg.Record], state: str
) -> asyncpg.Record | None:
    """Lit la ligne UNIQUEMENT si pending + non-expirée (pour le callback)."""
    return await conn.fetchrow(
        """
        SELECT * FROM oauth_pending_session
        WHERE state = $1 AND status = 'pending' AND expires_at > NOW()
        """,
        state,
    )


async def mark_authorized(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    result: dict[str, Any],
) -> int:
    return (
        await conn.fetchval(
            """
        UPDATE oauth_pending_session
        SET status = 'authorized', result = $2::jsonb
        WHERE state = $1 AND status = 'pending'
        RETURNING 1
        """,
            state,
            json.dumps(result),
        )
        or 0
    )


async def mark_failed(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    error: str,
) -> int:
    return (
        await conn.fetchval(
            """
        UPDATE oauth_pending_session
        SET status = 'failed', result = jsonb_build_object('error', $2::text)
        WHERE state = $1 AND status = 'pending'
        RETURNING 1
        """,
            state,
            error,
        )
        or 0
    )


async def delete_by_state(conn: asyncpg.Connection[asyncpg.Record], state: str) -> int:
    return await conn.fetchval(
        """
        WITH del AS (DELETE FROM oauth_pending_session WHERE state = $1 RETURNING 1)
        SELECT count(*) FROM del
        """,
        state,
    )


async def purge_expired(conn: asyncpg.Connection[asyncpg.Record]) -> int:
    """Supprime toutes les lignes dont expires_at est dans le passé. Retourne le compte."""
    return await conn.fetchval(
        """
        WITH del AS (DELETE FROM oauth_pending_session WHERE expires_at < NOW() RETURNING 1)
        SELECT count(*) FROM del
        """
    )
