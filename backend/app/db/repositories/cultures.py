"""Requêtes SQL pour la table cultures — langues ISO 639-1 activables (migration 034).

Requêtes écrites en entier, sans construction par f-string.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from app.models.db.culture import CultureRow


def _to_row(row: Any) -> CultureRow:
    return CultureRow(
        code=row["code"],
        english_name=row["english_name"],
        native_name=row["native_name"],
        enabled=row["enabled"],
        is_default=row["is_default"],
        updated_at=row["updated_at"],
    )


async def db_list(conn: asyncpg.Connection[asyncpg.Record]) -> list[CultureRow]:
    rows = await conn.fetch(
        """
        SELECT code, english_name, native_name, enabled, is_default, updated_at
          FROM cultures
         ORDER BY english_name ASC
        """
    )
    return [_to_row(r) for r in rows]


async def db_get(
    conn: asyncpg.Connection[asyncpg.Record],
    code: str,
    *,
    for_update: bool = False,
) -> CultureRow | None:
    if for_update:
        # Verrou : une modification lit l'état courant pour appliquer ses refus
        # (désactiver la culture par défaut…) ; sans lui, deux admins simultanés
        # décideraient chacun sur un état périmé.
        row = await conn.fetchrow(
            """
            SELECT code, english_name, native_name, enabled, is_default, updated_at
              FROM cultures
             WHERE code = $1
               FOR UPDATE
            """,
            code,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT code, english_name, native_name, enabled, is_default, updated_at
              FROM cultures
             WHERE code = $1
            """,
            code,
        )
    return _to_row(row) if row else None


async def db_set_enabled(
    conn: asyncpg.Connection[asyncpg.Record], code: str, enabled: bool
) -> CultureRow | None:
    row = await conn.fetchrow(
        """
        UPDATE cultures
           SET enabled = $2, updated_at = NOW()
         WHERE code = $1
        RETURNING code, english_name, native_name, enabled, is_default, updated_at
        """,
        code,
        enabled,
    )
    return _to_row(row) if row else None


async def db_clear_default(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """Retire le drapeau à l'ancienne culture par défaut — à appeler dans la même
    transaction que `db_mark_default`, sinon l'index unique partiel refuse la bascule."""
    await conn.execute(
        """
        UPDATE cultures
           SET is_default = FALSE, updated_at = NOW()
         WHERE is_default
        """
    )


async def db_mark_default(conn: asyncpg.Connection[asyncpg.Record], code: str) -> CultureRow | None:
    row = await conn.fetchrow(
        """
        UPDATE cultures
           SET is_default = TRUE, updated_at = NOW()
         WHERE code = $1
        RETURNING code, english_name, native_name, enabled, is_default, updated_at
        """,
        code,
    )
    return _to_row(row) if row else None
