"""Requêtes SQL pour la table listmonk_connection (migration 036), ligne unique.

Requêtes écrites en entier, sans construction par f-string.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from app.models.db.listmonk_connection import ListmonkConnectionRow


async def db_get(conn: asyncpg.Connection[asyncpg.Record]) -> ListmonkConnectionRow | None:
    row = await conn.fetchrow(
        """
        SELECT url, api_user, token_encrypted, updated_by_user_id, updated_at
          FROM listmonk_connection
        """
    )
    if row is None:
        return None
    return ListmonkConnectionRow(
        url=row["url"],
        api_user=row["api_user"],
        token_encrypted=bytes(row["token_encrypted"]),
        updated_by_user_id=row["updated_by_user_id"],
        updated_at=row["updated_at"],
    )


async def db_upsert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    url: str,
    api_user: str,
    token_encrypted: bytes,
    updated_by_user_id: UUID | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO listmonk_connection (id, url, api_user, token_encrypted, updated_by_user_id)
        VALUES (TRUE, $1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE
           SET url = EXCLUDED.url,
               api_user = EXCLUDED.api_user,
               token_encrypted = EXCLUDED.token_encrypted,
               updated_by_user_id = EXCLUDED.updated_by_user_id,
               updated_at = NOW()
        """,
        url,
        api_user,
        token_encrypted,
        updated_by_user_id,
    )


async def db_insert_if_absent(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    url: str,
    api_user: str,
    token_encrypted: bytes,
) -> bool:
    """Insère la connexion seulement s'il n'y en a pas : une connexion réglée depuis
    l'IHM n'est jamais écrasée par une reprise. Retourne True si la ligne a été posée."""
    inserted = await conn.fetchval(
        """
        INSERT INTO listmonk_connection (id, url, api_user, token_encrypted)
        VALUES (TRUE, $1, $2, $3)
        ON CONFLICT (id) DO NOTHING
        RETURNING TRUE
        """,
        url,
        api_user,
        token_encrypted,
    )
    return inserted is True
