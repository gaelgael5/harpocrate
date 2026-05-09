"""Repository — table wallet_environments (LOT_58)."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class EnvironmentRow:
    id: UUID
    owner_user_id: UUID
    name: str
    created_at: datetime.datetime


def _row_to_dto(row: asyncpg.Record) -> EnvironmentRow:
    return EnvironmentRow(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        created_at=row["created_at"],
    )


async def list_for_user(
    conn: asyncpg.Connection[asyncpg.Record],
    owner_user_id: UUID,
) -> list[EnvironmentRow]:
    rows = await conn.fetch(
        """
        SELECT id, owner_user_id, name, created_at
        FROM wallet_environments
        WHERE owner_user_id = $1
        ORDER BY name ASC
        """,
        owner_user_id,
    )
    return [_row_to_dto(r) for r in rows]


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    env_id: UUID,
) -> EnvironmentRow | None:
    row = await conn.fetchrow(
        """
        SELECT id, owner_user_id, name, created_at
        FROM wallet_environments
        WHERE id = $1
        """,
        env_id,
    )
    return _row_to_dto(row) if row else None


async def create(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    owner_user_id: UUID,
    name: str,
) -> UUID:
    """Crée un environnement. Lève UniqueViolationError si name déjà pris
    pour cet owner."""
    return await conn.fetchval(
        """
        INSERT INTO wallet_environments (owner_user_id, name)
        VALUES ($1, $2)
        RETURNING id
        """,
        owner_user_id,
        name.strip(),
    )


async def delete(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    env_id: UUID,
    owner_user_id: UUID,
) -> bool:
    """Supprime un env. Refuse si :
      - env n'appartient pas à cet owner (404 côté router)
      - env est encore référencé par des wallets (FK RESTRICT lève IntegrityError)
    Le router catch ces cas et remonte les bons codes HTTP.
    Retourne True si supprimé, False si pas trouvé.
    """
    result = await conn.execute(
        """
        DELETE FROM wallet_environments
        WHERE id = $1 AND owner_user_id = $2
        """,
        env_id,
        owner_user_id,
    )
    return str(result) != "DELETE 0"


async def count_wallets_using(
    conn: asyncpg.Connection[asyncpg.Record],
    env_id: UUID,
) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM wallets WHERE environment_id = $1",
        env_id,
    )
