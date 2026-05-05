"""Repository — secret_types et secret_schemas (LOT 15)."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg


async def list_types(
    conn: asyncpg.Connection,
    q: str | None = None,
    include_deprecated: bool = False,
) -> list[asyncpg.Record]:
    where_clauses: list[str] = []
    params: list[object] = []

    if q:
        params.append(f"%{q}%")
        idx = len(params)
        where_clauses.append(
            f"(t.type ILIKE ${idx} OR t.sous_type ILIKE ${idx} OR t.label ILIKE ${idx})"
        )

    if not include_deprecated:
        where_clauses.append("t.deprecated_at IS NULL")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    return await conn.fetch(
        f"""
        SELECT t.*,
               cv.version        AS cv_version,
               cv.created_at     AS cv_created_at,
               (SELECT COUNT(*) FROM secrets s WHERE s.type_uuid = t.type_uuid)
                                 AS used_count
        FROM secret_types t
        LEFT JOIN secret_schemas cv ON cv.version_uuid = t.current_version_uuid
        {where_sql}
        ORDER BY t.type, t.sous_type
        """,
        *params,
    )


async def get_type(conn: asyncpg.Connection, type_uuid: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT t.*,
               cv.version        AS cv_version,
               cv.schema_data    AS cv_schema_data,
               cv.schema_ui      AS cv_schema_ui,
               cv.notes          AS cv_notes,
               cv.created_at     AS cv_created_at,
               (SELECT COUNT(*) FROM secrets s WHERE s.type_uuid = t.type_uuid)
                                 AS used_count
        FROM secret_types t
        LEFT JOIN secret_schemas cv ON cv.version_uuid = t.current_version_uuid
        WHERE t.type_uuid = $1
        """,
        type_uuid,
    )


async def get_type_versions(conn: asyncpg.Connection, type_uuid: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT * FROM secret_schemas
        WHERE parent_uuid = $1
        ORDER BY version DESC
        """,
        type_uuid,
    )


async def get_version(conn: asyncpg.Connection, version_uuid: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM secret_schemas WHERE version_uuid = $1",
        version_uuid,
    )


async def insert_type_with_v1(
    conn: asyncpg.Connection,
    type_: str,
    sous_type: str,
    label: str | None,
    description: str | None,
    schema_data: dict,
    schema_ui: dict,
    notes: str | None,
    creator_id: UUID | None,
    is_system: bool = False,
) -> dict:
    async with conn.transaction():
        type_row = await conn.fetchrow(
            """INSERT INTO secret_types (type, sous_type, label, description, created_by_user_id, is_system)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING type_uuid""",
            type_,
            sous_type,
            label,
            description,
            creator_id,
            is_system,
        )
        type_uuid: UUID = type_row["type_uuid"]

        version_row = await conn.fetchrow(
            """INSERT INTO secret_schemas
               (parent_uuid, version, schema_data, schema_ui, notes, created_by_user_id)
               VALUES ($1, 1, $2::jsonb, $3::jsonb, $4, $5)
               RETURNING version_uuid""",
            type_uuid,
            json.dumps(schema_data),
            json.dumps(schema_ui),
            notes,
            creator_id,
        )
        version_uuid: UUID = version_row["version_uuid"]

        await conn.execute(
            "UPDATE secret_types SET current_version_uuid = $1 WHERE type_uuid = $2",
            version_uuid,
            type_uuid,
        )

    return {"type_uuid": type_uuid, "version_uuid": version_uuid}


async def insert_version(
    conn: asyncpg.Connection,
    type_uuid: UUID,
    schema_data: dict,
    schema_ui: dict,
    notes: str | None,
    set_as_current: bool,
    creator_id: UUID,
) -> dict:
    async with conn.transaction():
        await conn.execute(
            "SELECT 1 FROM secret_types WHERE type_uuid = $1 FOR UPDATE",
            type_uuid,
        )
        max_version = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM secret_schemas WHERE parent_uuid = $1",
            type_uuid,
        )
        new_version_num: int = max_version + 1

        version_row = await conn.fetchrow(
            """INSERT INTO secret_schemas
               (parent_uuid, version, schema_data, schema_ui, notes, created_by_user_id)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
               RETURNING version_uuid""",
            type_uuid,
            new_version_num,
            json.dumps(schema_data),
            json.dumps(schema_ui),
            notes,
            creator_id,
        )
        version_uuid: UUID = version_row["version_uuid"]

        if set_as_current:
            await conn.execute(
                "UPDATE secret_types SET current_version_uuid = $1 WHERE type_uuid = $2",
                version_uuid,
                type_uuid,
            )

    return {"version_uuid": version_uuid, "version": new_version_num}


async def update_type(
    conn: asyncpg.Connection,
    type_uuid: UUID,
    label: str | None = None,
    description: str | None = None,
    current_version_uuid: UUID | None = None,
    deprecated: bool | None = None,
) -> bool:
    sets: list[str] = []
    params: list[object] = [type_uuid]

    if label is not None:
        params.append(label)
        sets.append(f"label = ${len(params)}")
    if description is not None:
        params.append(description)
        sets.append(f"description = ${len(params)}")
    if current_version_uuid is not None:
        params.append(current_version_uuid)
        sets.append(f"current_version_uuid = ${len(params)}")
    if deprecated is True:
        sets.append("deprecated_at = NOW()")
    elif deprecated is False:
        sets.append("deprecated_at = NULL")

    if not sets:
        return True

    result = await conn.execute(
        f"UPDATE secret_types SET {', '.join(sets)} WHERE type_uuid = $1",
        *params,
    )
    return result == "UPDATE 1"


async def delete_type(conn: asyncpg.Connection, type_uuid: UUID) -> str:
    """Returns 'DELETE 1' or 'DELETE 0'."""
    return await conn.execute(
        "DELETE FROM secret_types WHERE type_uuid = $1",
        type_uuid,
    )


async def delete_version(conn: asyncpg.Connection, version_uuid: UUID) -> str:
    return await conn.execute(
        "DELETE FROM secret_schemas WHERE version_uuid = $1",
        version_uuid,
    )


async def get_raw_type_with_current_version_uuid(
    conn: asyncpg.Connection,
) -> tuple[UUID, UUID] | None:
    """Retourne (type_uuid, current_version_uuid) du type système RAW.

    Le type RAW est seedé au démarrage via app.services.seed_types depuis
    backend/types/raw/. None si pas encore seedé (cas de boot très précoce).
    """
    row = await conn.fetchrow(
        """SELECT type_uuid, current_version_uuid
           FROM secret_types
           WHERE type = 'raw' AND sous_type = 'raw' AND is_system = TRUE
           LIMIT 1"""
    )
    if row is None or row["current_version_uuid"] is None:
        return None
    return row["type_uuid"], row["current_version_uuid"]
