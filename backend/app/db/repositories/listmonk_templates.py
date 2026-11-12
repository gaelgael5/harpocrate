"""Requêtes SQL pour la table listmonk_templates (migration 035).

Requêtes écrites en entier, sans construction par f-string.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.listmonk_template import ListmonkTemplateRow, ResolvedTemplate


def _to_row(row: Any) -> ListmonkTemplateRow:
    return ListmonkTemplateRow(
        purpose=row["purpose"],
        culture_code=row["culture_code"],
        template_id=row["template_id"],
        updated_by_user_id=row["updated_by_user_id"],
        updated_at=row["updated_at"],
    )


async def db_list(conn: asyncpg.Connection[asyncpg.Record]) -> list[ListmonkTemplateRow]:
    rows = await conn.fetch(
        """
        SELECT purpose, culture_code, template_id, updated_by_user_id, updated_at
          FROM listmonk_templates
         ORDER BY purpose ASC, culture_code ASC
        """
    )
    return [_to_row(r) for r in rows]


async def db_get_for_update(
    conn: asyncpg.Connection[asyncpg.Record], purpose: str, culture_code: str
) -> ListmonkTemplateRow | None:
    """Ligne verrouillée : sa valeur précédente part dans l'audit, elle ne doit pas
    changer entre la lecture et l'écriture."""
    row = await conn.fetchrow(
        """
        SELECT purpose, culture_code, template_id, updated_by_user_id, updated_at
          FROM listmonk_templates
         WHERE purpose = $1 AND culture_code = $2
           FOR UPDATE
        """,
        purpose,
        culture_code,
    )
    return _to_row(row) if row else None


async def db_upsert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    purpose: str,
    culture_code: str,
    template_id: int,
    updated_by_user_id: UUID | None,
) -> ListmonkTemplateRow:
    row = await conn.fetchrow(
        """
        INSERT INTO listmonk_templates (purpose, culture_code, template_id, updated_by_user_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (purpose, culture_code) DO UPDATE
           SET template_id = EXCLUDED.template_id,
               updated_by_user_id = EXCLUDED.updated_by_user_id,
               updated_at = NOW()
        RETURNING purpose, culture_code, template_id, updated_by_user_id, updated_at
        """,
        purpose,
        culture_code,
        template_id,
        updated_by_user_id,
    )
    return _to_row(row)


async def db_delete(
    conn: asyncpg.Connection[asyncpg.Record], purpose: str, culture_code: str
) -> bool:
    deleted = await conn.fetchval(
        """
        DELETE FROM listmonk_templates
         WHERE purpose = $1 AND culture_code = $2
        RETURNING 1
        """,
        purpose,
        culture_code,
    )
    return deleted is not None


async def db_resolve(
    conn: asyncpg.Connection[asyncpg.Record], purpose: str, culture_code: str | None
) -> ResolvedTemplate | None:
    """Template de la culture demandée si elle est activée et pourvue, sinon celui de la
    culture par défaut, sinon None. Une seule requête : la culture par défaut lue ici est
    celle du même instant que la culture demandée."""
    row = await conn.fetchrow(
        """
        SELECT t.template_id, t.culture_code
          FROM listmonk_templates t
          JOIN cultures c ON c.code = t.culture_code
         WHERE t.purpose = $1
           AND c.enabled
           AND (c.code = $2 OR c.is_default)
         ORDER BY (c.code = $2) DESC NULLS LAST
         LIMIT 1
        """,
        purpose,
        culture_code,
    )
    if row is None:
        return None
    return ResolvedTemplate(template_id=row["template_id"], culture_code=row["culture_code"])


async def db_import_legacy(
    conn: asyncpg.Connection[asyncpg.Record],
    purpose: str,
    templates: dict[str, int],
) -> int:
    """Insère `templates` (culture → ID) seulement si aucun template n'existe encore pour
    `purpose`. Retourne le nombre de lignes insérées.

    La condition et l'insertion tiennent dans une seule instruction, et ON CONFLICT
    absorbe deux instances qui démarrent en même temps : l'idempotence se joue à
    l'écriture, pas sur une lecture préalable.
    """
    inserted = await conn.fetch(
        """
        INSERT INTO listmonk_templates (purpose, culture_code, template_id)
        SELECT $1, v.culture_code, v.template_id
          FROM unnest($2::text[], $3::int[]) AS v(culture_code, template_id)
         WHERE NOT EXISTS (SELECT 1 FROM listmonk_templates WHERE purpose = $1)
        ON CONFLICT (purpose, culture_code) DO NOTHING
        RETURNING culture_code
        """,
        purpose,
        list(templates.keys()),
        list(templates.values()),
    )
    return len(inserted)
