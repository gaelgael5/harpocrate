"""Endpoints /v1/admin/secret-types/* — LOT_15.

Admin CRUD pour les types de secrets et leurs versions de schéma.
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.core.admin_auth import AdminJwt
from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import secret_types as repo
from app.services import secret_types as svc
from app.services.secret_types import InvalidSchemaError

router = APIRouter(prefix="/admin/secret-types", tags=["admin-secret-types"])
public_router = APIRouter(prefix="/secret-types", tags=["secret-types"])


# ─── Models ──────────────────────────────────────────────────────────────────


class SecretTypeCreate(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    sous_type: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    schema_data: dict
    schema_ui: dict = Field(default_factory=dict)
    notes: str | None = None

    @field_validator("type", "sous_type")
    @classmethod
    def lowercase_strip(cls, v: str) -> str:
        return v.strip().lower()


class SecretTypeUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    current_version_uuid: UUID | None = None
    deprecated: bool | None = None


class SchemaVersionCreate(BaseModel):
    schema_data: dict
    schema_ui: dict = Field(default_factory=dict)
    notes: str | None = None
    set_as_current: bool = True


class SchemaVersionUpdateNotes(BaseModel):
    notes: str | None = None


class ValidateSchemaBody(BaseModel):
    schema_data: dict


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _type_list_item(r: object) -> dict:
    from asyncpg import Record
    rec: Record = r  # type: ignore[assignment]
    current_version = None
    if rec["current_version_uuid"] is not None:
        current_version = {
            "version_uuid": str(rec["current_version_uuid"]),
            "version": rec["cv_version"],
            "created_at": rec["cv_created_at"].isoformat() if rec["cv_created_at"] else None,
        }
    return {
        "type_uuid": str(rec["type_uuid"]),
        "type": rec["type"],
        "sous_type": rec["sous_type"],
        "label": rec["label"],
        "description": rec["description"],
        "is_system": rec["is_system"],
        "deprecated_at": rec["deprecated_at"].isoformat() if rec["deprecated_at"] else None,
        "current_version": current_version,
        "used_by_secrets_count": rec["used_count"],
    }


def _version_dict(r: object) -> dict:
    from asyncpg import Record
    rec: Record = r  # type: ignore[assignment]
    sd = rec["schema_data"]
    su = rec["schema_ui"]
    return {
        "version_uuid": str(rec["version_uuid"]),
        "parent_uuid": str(rec["parent_uuid"]),
        "version": rec["version"],
        "schema_data": json.loads(sd) if isinstance(sd, str) else dict(sd),
        "schema_ui": json.loads(su) if isinstance(su, str) else dict(su),
        "notes": rec["notes"],
        "created_at": rec["created_at"].isoformat(),
    }


# ─── Admin endpoints ──────────────────────────────────────────────────────────


@router.post("/validate-schema", response_class=JSONResponse)
async def validate_schema(body: ValidateSchemaBody, admin: AdminJwt) -> JSONResponse:
    """Valide que schema_data est un JSON Schema 2020-12 valide."""
    try:
        svc.validate_json_schema(body.schema_data)
        return JSONResponse({"valid": True})
    except InvalidSchemaError as e:
        return JSONResponse({"valid": False, "error": str(e)})


@router.get("", response_class=JSONResponse)
async def list_types(
    admin: AdminJwt,
    q: str | None = Query(default=None),
    include_deprecated: bool = Query(default=False),
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await repo.list_types(conn, q=q, include_deprecated=include_deprecated)
    return JSONResponse({"types": [_type_list_item(r) for r in rows]})


@router.post("", status_code=status.HTTP_201_CREATED, response_class=JSONResponse)
async def create_type(body: SecretTypeCreate, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await svc.create_type(
                conn,
                creator_id=UUID(admin.keycloak_sub) if _is_uuid(admin.keycloak_sub) else None,  # type: ignore[arg-type]
                type_=body.type,
                sous_type=body.sous_type,
                label=body.label,
                description=body.description,
                schema_data=body.schema_data,
                schema_ui=body.schema_ui,
                notes=body.notes,
            )
        except InvalidSchemaError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json_schema", "message": str(e)},
            ) from e
        except Exception as e:
            _handle_db_error(e)

    return JSONResponse(
        {"type_uuid": str(result["type_uuid"]), "version_uuid": str(result["version_uuid"])},
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/{type_uuid}", response_class=JSONResponse)
async def get_type(type_uuid: UUID, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_type(conn, type_uuid)
        if not row:
            raise HTTPException(status_code=404, detail={"error": "type_not_found"})
        versions = await repo.get_type_versions(conn, type_uuid)

    result = _type_list_item(row)
    if row["current_version_uuid"] is not None:
        sd = row["cv_schema_data"]
        su = row["cv_schema_ui"]
        result["current_version_full"] = {
            "version_uuid": str(row["current_version_uuid"]),
            "version": row["cv_version"],
            "schema_data": json.loads(sd) if isinstance(sd, str) else dict(sd),
            "schema_ui": json.loads(su) if isinstance(su, str) else dict(su),
            "created_at": row["cv_created_at"].isoformat() if row["cv_created_at"] else None,
        }
    else:
        result["current_version_full"] = None
    result["all_versions"] = [_version_dict(v) for v in versions]
    return JSONResponse(result)


@router.patch("/{type_uuid}", response_class=JSONResponse)
async def update_type(type_uuid: UUID, body: SecretTypeUpdate, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_type(conn, type_uuid)
        if not row:
            raise HTTPException(status_code=404, detail={"error": "type_not_found"})

        # Vérifier que current_version_uuid appartient à ce type si fourni
        if body.current_version_uuid is not None:
            version_row = await repo.get_version(conn, body.current_version_uuid)
            if not version_row or version_row["parent_uuid"] != type_uuid:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "current_version_uuid_wrong_type"},
                )

        try:
            await repo.update_type(
                conn,
                type_uuid,
                label=body.label,
                description=body.description,
                current_version_uuid=body.current_version_uuid,
                deprecated=body.deprecated,
            )
        except Exception as e:
            _handle_db_error(e)

    return JSONResponse({"updated": True})


@router.delete("/{type_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_type(type_uuid: UUID, admin: AdminJwt) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await svc.delete_type(conn, type_uuid, actor_id=_admin_uuid(admin))
        except LookupError as e:
            raise HTTPException(status_code=404, detail={"error": "type_not_found"}) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail={"error": str(e)}) from e
        except ValueError as e:
            msg = str(e)
            if msg.startswith("secret_type_in_use:"):
                count = msg.split(":")[1]
                raise HTTPException(
                    status_code=409,
                    detail={"error": "secret_type_in_use", "count": int(count)},
                ) from e
            raise HTTPException(status_code=400, detail={"error": msg}) from e


# ─── Schema version endpoints ─────────────────────────────────────────────────


@router.post("/{type_uuid}/schemas", status_code=status.HTTP_201_CREATED)
async def add_schema_version(
    type_uuid: UUID, body: SchemaVersionCreate, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_type(conn, type_uuid)
        if not row:
            raise HTTPException(status_code=404, detail={"error": "type_not_found"})
        try:
            result = await svc.add_version(
                conn,
                type_uuid=type_uuid,
                creator_id=_admin_uuid(admin),
                schema_data=body.schema_data,
                schema_ui=body.schema_ui,
                notes=body.notes,
                set_as_current=body.set_as_current,
            )
        except InvalidSchemaError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json_schema", "message": str(e)},
            ) from e

    return JSONResponse(
        {"version_uuid": str(result["version_uuid"]), "version": result["version"]},
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/{type_uuid}/schemas/{version_uuid}", response_class=JSONResponse)
async def get_schema_version(
    type_uuid: UUID, version_uuid: UUID, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_version(conn, version_uuid)
        if not row or row["parent_uuid"] != type_uuid:
            raise HTTPException(status_code=404, detail={"error": "version_not_found"})
    return JSONResponse(_version_dict(row))


@router.patch("/{type_uuid}/schemas/{version_uuid}", response_class=JSONResponse)
async def update_schema_version_notes(
    type_uuid: UUID, version_uuid: UUID, body: SchemaVersionUpdateNotes, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_version(conn, version_uuid)
        if not row or row["parent_uuid"] != type_uuid:
            raise HTTPException(status_code=404, detail={"error": "version_not_found"})
        await conn.execute(
            "UPDATE secret_schemas SET notes = $1 WHERE version_uuid = $2",
            body.notes,
            version_uuid,
        )
    return JSONResponse({"updated": True})


@router.delete("/{type_uuid}/schemas/{version_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schema_version(
    type_uuid: UUID, version_uuid: UUID, admin: AdminJwt
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await svc.delete_version(conn, version_uuid, actor_id=_admin_uuid(admin))
        except LookupError as e:
            raise HTTPException(status_code=404, detail={"error": "version_not_found"}) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail={"error": str(e)}) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail={"error": str(e)}) from e


# ─── Public endpoint ──────────────────────────────────────────────────────────


@public_router.get("", response_class=JSONResponse)
async def list_secret_types_public(
    user: JwtUser,
    q: str | None = Query(default=None),
    include_deprecated: bool = Query(default=False),
) -> JSONResponse:
    """Liste publique des types de secrets (pour UI création de secret)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await repo.list_types(conn, q=q, include_deprecated=include_deprecated)
    return JSONResponse({"types": [_type_list_item(r) for r in rows]})


@public_router.get("/{type_uuid}", response_class=JSONResponse)
async def get_secret_type_public(type_uuid: UUID, user: JwtUser) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_type(conn, type_uuid)
        if not row:
            raise HTTPException(status_code=404, detail={"error": "type_not_found"})
        versions = await repo.get_type_versions(conn, type_uuid)
    result = _type_list_item(row)
    if row["current_version_uuid"] is not None:
        sd = row["cv_schema_data"]
        su = row["cv_schema_ui"]
        result["current_version_full"] = {
            "version_uuid": str(row["current_version_uuid"]),
            "version": row["cv_version"],
            "schema_data": json.loads(sd) if isinstance(sd, str) else dict(sd),
            "schema_ui": json.loads(su) if isinstance(su, str) else dict(su),
            "created_at": row["cv_created_at"].isoformat() if row["cv_created_at"] else None,
        }
    else:
        result["current_version_full"] = None
    result["all_versions"] = [_version_dict(v) for v in versions]
    return JSONResponse(result)


# ─── Utilities ────────────────────────────────────────────────────────────────


def _is_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except ValueError:
        return False


def _admin_uuid(admin: AdminJwt) -> UUID | None:  # type: ignore[return]
    if _is_uuid(admin.keycloak_sub):
        return UUID(admin.keycloak_sub)
    return None


def _handle_db_error(e: Exception) -> None:
    msg = str(e)
    if "unique" in msg.lower() or "23505" in msg:
        raise HTTPException(
            status_code=409,
            detail={"error": "secret_type_already_exists"},
        )
    raise HTTPException(status_code=500, detail={"error": "internal_error", "message": msg})
