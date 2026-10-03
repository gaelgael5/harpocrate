"""Requêtes SQL pour la table connect_clients — registre des applications (migration 033).

Requêtes écrites en entier, sans construction par f-string (règle « État en base » :
le motif « liste de colonnes en f-string » de certains repositories ne s'étend pas).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.connect_client import ConnectClientRow


def _to_row(row: Any) -> ConnectClientRow:
    return ConnectClientRow(
        id=row["id"],
        client_id=row["client_id"],
        name=row["name"],
        description=row["description"],
        redirect_uris=list(row["redirect_uris"]),
        active=row["active"],
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def db_insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    client_id: str,
    name: str,
    description: str | None,
    redirect_uris: list[str],
    created_by_user_id: UUID | None,
) -> ConnectClientRow:
    """Insère une application. Lève `asyncpg.UniqueViolationError` si `client_id` est pris :
    l'unicité se joue à l'écriture, jamais par une lecture préalable."""
    row = await conn.fetchrow(
        """
        INSERT INTO connect_clients
            (client_id, name, description, redirect_uris, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, client_id, name, description, redirect_uris, active,
                  created_by_user_id, created_at, updated_at
        """,
        client_id,
        name,
        description,
        redirect_uris,
        created_by_user_id,
    )
    return _to_row(row)


async def db_list(conn: asyncpg.Connection[asyncpg.Record]) -> list[ConnectClientRow]:
    rows = await conn.fetch(
        """
        SELECT id, client_id, name, description, redirect_uris, active,
               created_by_user_id, created_at, updated_at
          FROM connect_clients
         ORDER BY LOWER(name) ASC, client_id ASC
        """
    )
    return [_to_row(r) for r in rows]


async def db_get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    client_pk: UUID,
    *,
    for_update: bool = False,
) -> ConnectClientRow | None:
    if for_update:
        # Une modification lit puis réécrit la ligne entière : le verrou empêche deux
        # modifications concurrentes de s'écraser l'une l'autre.
        row = await conn.fetchrow(
            """
            SELECT id, client_id, name, description, redirect_uris, active,
                   created_by_user_id, created_at, updated_at
              FROM connect_clients
             WHERE id = $1
               FOR UPDATE
            """,
            client_pk,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT id, client_id, name, description, redirect_uris, active,
                   created_by_user_id, created_at, updated_at
              FROM connect_clients
             WHERE id = $1
            """,
            client_pk,
        )
    return _to_row(row) if row else None


async def db_get_active_by_client_id(
    conn: asyncpg.Connection[asyncpg.Record], client_id: str
) -> ConnectClientRow | None:
    """Application ACTIVE par identifiant public : une application désactivée ne peut plus
    lancer de demande de connexion."""
    row = await conn.fetchrow(
        """
        SELECT id, client_id, name, description, redirect_uris, active,
               created_by_user_id, created_at, updated_at
          FROM connect_clients
         WHERE client_id = $1 AND active
        """,
        client_id,
    )
    return _to_row(row) if row else None


async def db_update(
    conn: asyncpg.Connection[asyncpg.Record],
    client_pk: UUID,
    *,
    name: str,
    description: str | None,
    redirect_uris: list[str],
    active: bool,
) -> ConnectClientRow | None:
    """Réécrit tous les champs modifiables (le service fusionne la modification partielle)."""
    row = await conn.fetchrow(
        """
        UPDATE connect_clients
           SET name = $2, description = $3, redirect_uris = $4, active = $5, updated_at = NOW()
         WHERE id = $1
        RETURNING id, client_id, name, description, redirect_uris, active,
                  created_by_user_id, created_at, updated_at
        """,
        client_pk,
        name,
        description,
        redirect_uris,
        active,
    )
    return _to_row(row) if row else None
