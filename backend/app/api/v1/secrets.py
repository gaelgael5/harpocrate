"""Endpoints /v1/wallets/{wallet_id}/secrets/* — LOT_05.

NOTE SÉCURITÉ — Body jamais loggé :
  Le middleware log_requests dans app/main.py détecte les chemins /secrets et
  positionne body_logged=False. Aucun handler ne lit ni ne logue request.body().

Auth mixte (JWT ou API key hrpv_*) sur tous les endpoints selon permission requise.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.core.api_key_auth import (
    AuthContext,
    require_any_auth_with_any_of_permissions,
    require_any_auth_with_permission,
)
from app.db.pool import get_pool
from app.db.repositories import secrets as secrets_repo
from app.models.api.secrets import (
    PlaceholderCreateRequest,
    PopulateRequest,
    SecretCreateRequest,
    SecretPatchRequest,
    SecretPutRequest,
)
from app.models.db.secret import SecretRow
from app.services import secrets as secrets_svc
from app.services.permissions import PERM_ADD, PERM_INIT, PERM_READ, PERM_REMOVE, PERM_WRITE
from app.services.secret_paths import normalize_path

router = APIRouter(
    prefix="/wallets/{wallet_id}/secrets",
    tags=["secrets"],
)

# ─── Auth shorthands ──────────────────────────────────────────────────────────

ReadAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_READ))]
AddAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_ADD))]
WriteAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_WRITE))]
InitAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_INIT))]
RemoveAuth = Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_REMOVE))]
DescriptorAuth = Annotated[
    AuthContext,
    Depends(require_any_auth_with_any_of_permissions(PERM_READ | PERM_INIT)),
]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _secret_to_dict(s: SecretRow) -> dict[str, object]:
    return {
        "id": str(s.id),
        "wallet_id": str(s.wallet_id),
        "name": s.name,
        "description": s.description,
        "is_placeholder": s.is_placeholder,
        "generation_version": s.generation_version,
        "tags": s.tags,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── GET /v1/wallets/{wallet_id}/secrets ──────────────────────────────────────


@router.get("")
async def list_secrets(
    wallet_id: UUID,
    auth: ReadAuth,
    request: Request,
    path: str | None = Query(default=None, description="Filtrer par répertoire"),
    tag: str | None = Query(default=None),
    name_contains: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
    """Liste les secrets du wallet (sans encrypted_value). Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if path is not None:
            cursor_updated_at, cursor_id = None, None
            if cursor:
                try:
                    cursor_updated_at, cursor_id = secrets_repo.decode_cursor(cursor)
                except ValueError:
                    return JSONResponse(status_code=400, content={"error": "invalid_cursor"})

            normalized = normalize_path(path)
            rows = await secrets_repo.list_by_path(
                conn,
                wallet_id=wallet_id,
                path=normalized,
                limit=limit,
                cursor_updated_at=cursor_updated_at,
                cursor_id=cursor_id,
            )
            next_cursor = None
            if len(rows) == limit:
                last = rows[-1]
                next_cursor = secrets_repo.encode_cursor(last.updated_at, last.id)

            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "secrets": [_secret_to_dict(s) for s in rows],
                    "next_cursor": next_cursor,
                },
            )

        result = await secrets_svc.list_secrets(
            conn,
            wallet_id=wallet_id,
            caller_user_id=auth.caller_user_id,
            limit=limit,
            cursor=cursor,
            tag_filter=tag,
            name_contains=name_contains,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── By-ID — accès par UUID (contourne les soucis de routing pour noms à '/') ─


@router.get("/by-id/{secret_id}")
async def get_secret_by_id(
    wallet_id: UUID,
    secret_id: UUID,
    auth: ReadAuth,
    request: Request,
) -> JSONResponse:
    """Retourne le secret par UUID. Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.get_secret_by_id(
            conn,
            wallet_id=wallet_id,
            secret_id=secret_id,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── PUT /v1/wallets/{wallet_id}/secrets/by-id/{secret_id} ───────────────────


@router.put("/by-id/{secret_id}")
async def put_secret_by_id(
    wallet_id: UUID,
    secret_id: UUID,
    req: SecretPutRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Remplace encrypted_value par UUID. Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.put_secret_by_id(
            conn,
            wallet_id=wallet_id,
            secret_id=secret_id,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── GET /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────────


@router.get("/{name}")
async def get_secret(
    wallet_id: UUID,
    name: str,
    auth: ReadAuth,
    request: Request,
) -> JSONResponse:
    """Retourne le secret (encrypted_value + encrypted_wallet_key du caller). Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.get_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── POST /v1/wallets/{wallet_id}/secrets ─────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_secret(
    wallet_id: UUID,
    req: SecretCreateRequest,
    auth: AddAuth,
    request: Request,
) -> JSONResponse:
    """Crée un secret. Body JAMAIS loggé (voir middleware log_requests). Requiert [add]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.create_secret(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_201_CREATED, content=result.model_dump(mode="json"))


# ─── PUT /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────────


@router.put("/{name}")
async def put_secret(
    wallet_id: UUID,
    name: str,
    req: SecretPutRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Remplace encrypted_value, incrémente generation_version. Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.put_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── PATCH /v1/wallets/{wallet_id}/secrets/{name} ────────────────────────────


@router.patch("/{name}")
async def patch_secret(
    wallet_id: UUID,
    name: str,
    req: SecretPatchRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Met à jour description/tags uniquement (pas la valeur). Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await secrets_svc.patch_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ─── POST /v1/wallets/{wallet_id}/secrets/placeholder ────────────────────────

# IMPORTANT : cette route doit être déclarée AVANT "/{name}" pour que FastAPI
# ne l'interprète pas comme un secret nommé "placeholder".


@router.post("/placeholder", status_code=status.HTTP_201_CREATED)
async def create_placeholder(
    wallet_id: UUID,
    req: PlaceholderCreateRequest,
    auth: AddAuth,
    request: Request,
) -> JSONResponse:
    """Crée un secret placeholder avec descripteur de génération. Requiert [add]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.create_placeholder(
            conn,
            wallet_id=wallet_id,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_201_CREATED, content=result.model_dump(mode="json"))


# ─── POST /v1/wallets/{wallet_id}/secrets/{name}/populate ────────────────────


@router.post("/{name}/populate")
async def populate_secret(
    wallet_id: UUID,
    name: str,
    req: PopulateRequest,
    auth: InitAuth,
    request: Request,
) -> JSONResponse:
    """Peuple un placeholder avec sa valeur chiffrée. Requiert [init]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.populate_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── GET /v1/wallets/{wallet_id}/secrets/{name}/descriptor ───────────────────


@router.get("/{name}/descriptor")
async def get_descriptor(
    wallet_id: UUID,
    name: str,
    auth: DescriptorAuth,
    request: Request,
) -> JSONResponse:
    """Retourne le descripteur de génération du placeholder. Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.get_descriptor(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))


# ─── DELETE /v1/wallets/{wallet_id}/secrets/by-id/{secret_id} ────────────────


@router.delete(
    "/by-id/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_secret_by_id(
    wallet_id: UUID,
    secret_id: UUID,
    auth: RemoveAuth,
    request: Request,
) -> Response:
    """Supprime le secret par UUID (cascade sur secret_tags + path_index). Requiert [remove]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await secrets_svc.delete_secret_by_id(
            conn,
            wallet_id=wallet_id,
            secret_id=secret_id,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── DELETE /v1/wallets/{wallet_id}/secrets/{name} ───────────────────────────


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_secret(
    wallet_id: UUID,
    name: str,
    auth: RemoveAuth,
    request: Request,
) -> Response:
    """Supprime le secret (cascade sur secret_tags). Requiert [remove]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await secrets_svc.delete_secret(
            conn,
            wallet_id=wallet_id,
            name=name,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── LOT_17 — Typed secrets ───────────────────────────────────────────────────


class MigrateSchemaRequest(BaseModel):
    encrypted_value: str  # base64
    target_schema_version_uuid: UUID


class AssignTypeRequest(BaseModel):
    type_uuid: UUID
    schema_version_uuid: UUID
    encrypted_value: str  # base64


@router.patch("/{name}/migrate-schema")
async def migrate_schema(
    wallet_id: UUID,
    name: str,
    req: MigrateSchemaRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Migre un secret vers une nouvelle version de son schéma. JWT uniquement (pas API key)."""
    if auth.is_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "jwt_only", "message": "Schema migration requires a JWT token"},
        )

    import base64 as _b64

    try:
        enc_value = _b64.b64decode(req.encrypted_value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64"},
        ) from exc

    pool = await get_pool()
    async with pool.acquire() as conn:
        secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
        if secret is None:
            raise HTTPException(status_code=404, detail={"error": "secret_not_found"})
        if secret.type_uuid is None:
            raise HTTPException(
                status_code=400,
                detail={"error": "secret_has_no_type_cannot_migrate"},
            )

        # Vérifier que target_schema_version_uuid appartient au même type
        target_row = await conn.fetchrow(
            "SELECT parent_uuid FROM secret_schemas WHERE version_uuid = $1",
            req.target_schema_version_uuid,
        )
        if target_row is None or target_row["parent_uuid"] != secret.type_uuid:
            raise HTTPException(
                status_code=400,
                detail={"error": "schema_version_does_not_belong_to_type"},
            )

        # P1.5 : refuser de migrer vers une version d'un type deprecated
        from app.db.repositories import secret_types as types_repo

        target_type = await types_repo.get_type(conn, secret.type_uuid)
        if target_type is not None and target_type["deprecated_at"] is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "deprecated_type",
                    "message": "Cannot migrate to a version of a deprecated type",
                },
            )

        await conn.execute(
            """UPDATE secrets
               SET encrypted_value = $1,
                   schema_version_uuid = $2,
                   generation_version = generation_version + 1,
                   updated_at = NOW(),
                   updated_by_user_id = $3
               WHERE id = $4""",
            enc_value,
            req.target_schema_version_uuid,
            auth.caller_user_id,
            secret.id,
        )
        from app.services.audit import audit_log_insert

        await audit_log_insert(
            conn,
            "secret.schema_migrated",
            actor_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={
                "from_version_uuid": str(secret.schema_version_uuid),
                "to_version_uuid": str(req.target_schema_version_uuid),
            },
        )

    return JSONResponse({"migrated": True})


@router.patch("/{name}/assign-type")
async def assign_type(
    wallet_id: UUID,
    name: str,
    req: AssignTypeRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Assigne un type à un secret legacy. JWT uniquement (pas API key)."""
    if auth.is_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "jwt_only", "message": "Type assignment requires a JWT token"},
        )

    import base64 as _b64

    try:
        enc_value = _b64.b64decode(req.encrypted_value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64"},
        ) from exc

    pool = await get_pool()
    async with pool.acquire() as conn:
        secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
        if secret is None:
            raise HTTPException(status_code=404, detail={"error": "secret_not_found"})

        # Vérifier cohérence type/schema
        schema_row = await conn.fetchrow(
            "SELECT parent_uuid FROM secret_schemas WHERE version_uuid = $1",
            req.schema_version_uuid,
        )
        if schema_row is None or schema_row["parent_uuid"] != req.type_uuid:
            raise HTTPException(
                status_code=400,
                detail={"error": "schema_version_does_not_belong_to_type"},
            )

        # P1.5 : refuser d'assigner un type deprecated
        from app.db.repositories import secret_types as types_repo

        target_type = await types_repo.get_type(conn, req.type_uuid)
        if target_type is not None and target_type["deprecated_at"] is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "deprecated_type",
                    "message": "Cannot assign a deprecated type to a secret",
                },
            )

        await conn.execute(
            """UPDATE secrets
               SET encrypted_value = $1,
                   type_uuid = $2,
                   schema_version_uuid = $3,
                   generation_version = generation_version + 1,
                   updated_at = NOW(),
                   updated_by_user_id = $4
               WHERE id = $5""",
            enc_value,
            req.type_uuid,
            req.schema_version_uuid,
            auth.caller_user_id,
            secret.id,
        )
        from app.services.audit import audit_log_insert

        await audit_log_insert(
            conn,
            "secret.type_assigned",
            actor_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={
                "type_uuid": str(req.type_uuid),
                "schema_version_uuid": str(req.schema_version_uuid),
            },
        )

    return JSONResponse({"assigned": True})
