"""Service — types de secrets et schemas (LOT 15)."""
from __future__ import annotations

from uuid import UUID

import asyncpg
from jsonschema import Draft202012Validator
from jsonschema import exceptions as js_exc

from app.db.repositories import secret_types as repo
from app.services.audit import audit_log_insert


class InvalidSchemaError(ValueError):
    pass


def validate_json_schema(schema_data: dict) -> None:
    try:
        Draft202012Validator.check_schema(schema_data)
    except js_exc.SchemaError as e:
        raise InvalidSchemaError(str(e)) from e


async def create_type(
    conn: asyncpg.Connection,
    creator_id: UUID,
    type_: str,
    sous_type: str,
    label: str | None,
    description: str | None,
    schema_data: dict,
    schema_ui: dict,
    notes: str | None,
) -> dict:
    validate_json_schema(schema_data)
    result = await repo.insert_type_with_v1(
        conn,
        type_=type_,
        sous_type=sous_type,
        label=label,
        description=description,
        schema_data=schema_data,
        schema_ui=schema_ui,
        notes=notes,
        creator_id=creator_id,
    )
    await audit_log_insert(
        conn,
        "secret_type.created",
        actor_user_id=creator_id,
        metadata={
            "type_uuid": str(result["type_uuid"]),
            "type": type_,
            "sous_type": sous_type,
        },
    )
    return result


async def add_version(
    conn: asyncpg.Connection,
    type_uuid: UUID,
    creator_id: UUID,
    schema_data: dict,
    schema_ui: dict,
    notes: str | None,
    set_as_current: bool,
) -> dict:
    validate_json_schema(schema_data)
    result = await repo.insert_version(
        conn,
        type_uuid=type_uuid,
        schema_data=schema_data,
        schema_ui=schema_ui,
        notes=notes,
        set_as_current=set_as_current,
        creator_id=creator_id,
    )
    await audit_log_insert(
        conn,
        "secret_type.version_added",
        actor_user_id=creator_id,
        metadata={
            "type_uuid": str(type_uuid),
            "version_uuid": str(result["version_uuid"]),
            "version": result["version"],
            "set_as_current": set_as_current,
        },
    )
    return result


async def delete_type(
    conn: asyncpg.Connection,
    type_uuid: UUID,
    actor_id: UUID,
) -> None:
    type_row = await repo.get_type(conn, type_uuid)
    if not type_row:
        raise LookupError("type_not_found")
    if type_row["is_system"]:
        raise PermissionError("cannot_delete_system_type")
    used = type_row["used_count"]
    if used > 0:
        raise ValueError(f"secret_type_in_use:{used}")

    await repo.delete_type(conn, type_uuid)
    await audit_log_insert(
        conn,
        "secret_type.deleted",
        actor_user_id=actor_id,
        metadata={"type_uuid": str(type_uuid)},
    )


async def delete_version(
    conn: asyncpg.Connection,
    version_uuid: UUID,
    actor_id: UUID,
) -> None:
    version_row = await repo.get_version(conn, version_uuid)
    if not version_row:
        raise LookupError("version_not_found")

    type_row = await repo.get_type(conn, version_row["parent_uuid"])
    if type_row and type_row["is_system"]:
        raise PermissionError("cannot_delete_system_type")
    if type_row and type_row["current_version_uuid"] == version_uuid:
        raise ValueError("cannot_delete_current_version")

    await repo.delete_version(conn, version_uuid)
    await audit_log_insert(
        conn,
        "secret_type.version_deleted",
        actor_user_id=actor_id,
        metadata={
            "type_uuid": str(version_row["parent_uuid"]),
            "version_uuid": str(version_uuid),
        },
    )
