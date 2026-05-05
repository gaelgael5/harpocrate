"""Service secrets — logique métier CRUD secrets (LOT_05/06)."""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.db.repositories import secrets as secrets_repo
from app.models.api.generators import GenerationDescriptor
from app.models.api.secrets import (
    DescriptorResponse,
    PlaceholderCreateRequest,
    PopulateRequest,
    PopulateResponse,
    SecretCreateRequest,
    SecretCreateResponse,
    SecretDetailResponse,
    SecretListItem,
    SecretListResponse,
    SecretPatchRequest,
    SecretPutRequest,
    SecretPutResponse,
    _CallerRef,
)
from app.models.db.secret import SecretRow
from app.services.audit import audit_log_insert

# ─── Helpers privés ───────────────────────────────────────────────────────────

_DEFAULT_LIMIT = 50


def _secret_list_item(row: SecretRow) -> SecretListItem:
    created_by: _CallerRef | None = None
    if row.created_by_user_id is not None:
        created_by = _CallerRef(type="user", id=row.created_by_user_id)
    elif row.created_by_api_key_id is not None:
        created_by = _CallerRef(type="api_key", id=row.created_by_api_key_id)

    updated_by: _CallerRef | None = None
    if row.updated_by_user_id is not None:
        updated_by = _CallerRef(type="user", id=row.updated_by_user_id)
    elif row.updated_by_api_key_id is not None:
        updated_by = _CallerRef(type="api_key", id=row.updated_by_api_key_id)

    return SecretListItem(
        id=row.id,
        name=row.name,
        description=row.description,
        tags=sorted(row.tags),
        is_placeholder=row.is_placeholder,
        generation_version=row.generation_version,
        linked_secret_id=row.linked_secret_id,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        created_by=created_by,
        updated_by=updated_by,
    )


# ─── List secrets ─────────────────────────────────────────────────────────────


async def list_secrets(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    caller_user_id: UUID,
    limit: int,
    cursor: str | None,
    tag_filter: str | None,
    name_contains: str | None,
) -> SecretListResponse:
    """Liste les secrets du wallet (sans valeur). Accès vérifié par la couche auth."""
    cursor_updated_at = None
    cursor_id = None
    if cursor:
        try:
            cursor_updated_at, cursor_id = secrets_repo.decode_cursor(cursor)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_cursor", "message": "Malformed pagination cursor"},
            ) from exc

    rows = await secrets_repo.list_secrets(
        conn,
        wallet_id=wallet_id,
        limit=limit,
        cursor_updated_at=cursor_updated_at,
        cursor_id=cursor_id,
        tag_filter=tag_filter,
        name_contains=name_contains,
    )

    next_cursor: str | None = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = secrets_repo.encode_cursor(last.updated_at, last.id)

    return SecretListResponse(
        secrets=[_secret_list_item(r) for r in rows],
        next_cursor=next_cursor,
    )


# ─── Get secret ───────────────────────────────────────────────────────────────


async def get_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretDetailResponse:
    """Retourne le secret avec encrypted_value + encrypted_wallet_key du caller."""
    secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    # LOT_06 : placeholder → 424 Failed Dependency avec descripteur
    if secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail={
                "error": "placeholder_value_missing",
                "message": "Secret has no value yet, populate it first.",
                "details": {
                    "name": secret.name,
                    "is_placeholder": True,
                    "generation_descriptor": secret.generation_descriptor,
                },
            },
        )

    enc_wallet_key_bytes = await secrets_repo.get_caller_encrypted_wallet_key(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if enc_wallet_key_bytes is None:  # pragma: no cover — grant vérifié juste avant
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "grant_key_missing", "message": "Encrypted wallet key not found"},
        )

    await audit_log_insert(
        conn,
        "secret.read",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        target_secret_id=secret.id,
        metadata={"secret_name": secret.name},
    )

    enc_value_b64 = base64.b64encode(secret.encrypted_value or b"").decode()
    enc_key_b64 = base64.b64encode(enc_wallet_key_bytes).decode()

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        encrypted_value=enc_value_b64,
        encrypted_wallet_key=enc_key_b64,
        description=secret.description,
        tags=sorted(secret.tags),
        is_placeholder=secret.is_placeholder,
        generation_version=secret.generation_version,
        type_uuid=secret.type_uuid,
        schema_version_uuid=secret.schema_version_uuid,
    )


# ─── Create secret ────────────────────────────────────────────────────────────


async def create_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    req: SecretCreateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretCreateResponse:
    """Crée un secret. Accès vérifié par la couche auth."""
    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — validé par Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    # ─── P1.5 : résolution du type ────────────────────────────────────────────
    from app.db.repositories import secret_types as types_repo

    type_uuid = req.type_uuid
    schema_version_uuid = req.schema_version_uuid

    if type_uuid is None:
        # Pas de type fourni → on attache automatiquement RAW
        raw = await types_repo.get_raw_type_with_current_version_uuid(conn)
        if raw is None:  # pragma: no cover — RAW est seedé au boot
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "raw_type_unavailable", "message": "System type RAW not seeded"},
            )
        type_uuid, schema_version_uuid = raw
    else:
        # Type fourni explicitement → vérifier qu'il n'est pas deprecated
        type_row = await types_repo.get_type(conn, type_uuid)
        if type_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "type_not_found", "message": f"Type {type_uuid} does not exist"},
            )
        if type_row["deprecated_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "deprecated_type",
                    "message": f"Type {type_uuid} is deprecated and cannot be used for new secrets",
                },
            )

    try:
        async with conn.transaction():
            secret_id = await secrets_repo.insert_secret(
                conn,
                wallet_id=wallet_id,
                name=req.name,
                description=req.description,
                encrypted_value=enc_value,
                tags=req.tags,
                created_by_user_id=caller_user_id,
                type_uuid=type_uuid,
                schema_version_uuid=schema_version_uuid,
            )
            await audit_log_insert(
                conn,
                "secret.created",
                actor_user_id=caller_user_id,
                actor_ip=actor_ip,
                target_wallet_id=wallet_id,
                target_secret_id=secret_id,
                metadata={"secret_name": req.name, "type_uuid": str(type_uuid)},
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "secret_name_exists",
                "message": f"A secret named '{req.name}' already exists in this wallet.",
            },
        ) from exc

    return SecretCreateResponse(secret_id=secret_id)


# ─── Update secret value (PUT) ────────────────────────────────────────────────


async def put_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    req: SecretPutRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretPutResponse:
    """Remplace encrypted_value, incrémente generation_version. Accès vérifié par la couche auth."""
    secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    # LOT_06 : PUT sur un placeholder → 409 (utiliser populate à la place)
    if secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "placeholder_expected",
                "message": (
                    "This secret is a placeholder. "
                    "Use POST /populate (permission [init]) to set its value."
                ),
            },
        )

    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — validé par Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    async with conn.transaction():
        new_version = await secrets_repo.update_secret_value(
            conn,
            secret_id=secret.id,
            encrypted_value=enc_value,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": name, "field": "encrypted_value"},
        )

    return SecretPutResponse(generation_version=new_version)


# ─── Update secret metadata (PATCH) ──────────────────────────────────────────


async def patch_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    req: SecretPatchRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Met à jour description/tags sans toucher à la valeur. Accès vérifié par la couche auth."""
    secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    async with conn.transaction():
        await secrets_repo.update_secret_meta(
            conn,
            secret_id=secret.id,
            description=req.description,
            tags=req.tags,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": name, "field": "metadata"},
        )


# ─── Delete secret ────────────────────────────────────────────────────────────


async def delete_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Supprime le secret. Accès vérifié par la couche auth."""
    secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    async with conn.transaction():
        await secrets_repo.delete_secret(conn, secret_id=secret.id)
        await audit_log_insert(
            conn,
            "secret.deleted",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": name},
        )


# ─── LOT_06 — Create placeholder ──────────────────────────────────────────────


async def create_placeholder(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    req: PlaceholderCreateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretCreateResponse:
    """Crée un secret placeholder avec descripteur de génération. Accès vérifié par la couche auth."""  # noqa: E501
    # Validation linked_secret_id : doit appartenir au même wallet
    if req.linked_secret_id is not None:
        linked_wallet_id: UUID | None = await conn.fetchval(
            "SELECT wallet_id FROM secrets WHERE id = $1",
            req.linked_secret_id,
        )
        if linked_wallet_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "linked_secret_not_found",
                    "message": "linked_secret_id does not refer to an existing secret.",
                },
            )
        if linked_wallet_id != wallet_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "linked_secret_must_be_in_same_wallet",
                    "message": "linked_secret_id must point to a secret in the same wallet.",
                },
            )

    descriptor_dict: dict[str, Any] = req.generation_descriptor.model_dump()

    try:
        async with conn.transaction():
            secret_id = await secrets_repo.insert_placeholder(
                conn,
                wallet_id=wallet_id,
                name=req.name,
                description=req.description,
                generation_descriptor=descriptor_dict,
                tags=req.tags,
                linked_secret_id=req.linked_secret_id,
                created_by_user_id=caller_user_id,
            )
            await audit_log_insert(
                conn,
                "secret.placeholder_created",
                actor_user_id=caller_user_id,
                actor_ip=actor_ip,
                target_wallet_id=wallet_id,
                target_secret_id=secret_id,
                metadata={
                    "secret_name": req.name,
                    "generator_type": descriptor_dict.get("type"),
                },
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "secret_name_exists",
                "message": f"A secret named '{req.name}' already exists in this wallet.",
            },
        ) from exc

    return SecretCreateResponse(secret_id=secret_id)


# ─── LOT_06 — Populate placeholder ───────────────────────────────────────────


async def populate_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    req: PopulateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> PopulateResponse:
    """Peuple un placeholder avec sa valeur chiffrée. Accès vérifié par la couche auth."""
    secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if not secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "secret_already_populated",
                "message": (
                    "This secret already has a value. Use PUT (permission [write]) to update it."
                ),
            },
        )

    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — validé par Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    descriptor_type = (secret.generation_descriptor or {}).get("type")

    async with conn.transaction():
        new_version = await secrets_repo.populate_secret(
            conn,
            secret_id=secret.id,
            encrypted_value=enc_value,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.populated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": name, "generator_type": descriptor_type},
        )

    return PopulateResponse(generation_version=new_version)


async def get_descriptor_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> DescriptorResponse:
    """Retourne le descripteur d'un placeholder par UUID."""
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if not secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "secret_not_placeholder",
                "message": "This secret is not a placeholder; it has no generation descriptor.",
            },
        )

    await audit_log_insert(
        conn,
        "secret.descriptor_accessed",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        target_secret_id=secret.id,
        metadata={"secret_name": secret.name, "access_via": "by_id"},
    )

    descriptor: GenerationDescriptor | None = None
    if secret.generation_descriptor is not None:
        from pydantic import TypeAdapter

        _ta: TypeAdapter[GenerationDescriptor] = TypeAdapter(GenerationDescriptor)
        descriptor = _ta.validate_python(secret.generation_descriptor)

    return DescriptorResponse(
        name=secret.name,
        is_placeholder=secret.is_placeholder,
        generation_descriptor=descriptor,
        generation_version=secret.generation_version,
        linked_secret_id=secret.linked_secret_id,
    )


# ─── LOT_06 — Get descriptor ──────────────────────────────────────────────────


async def get_descriptor(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> DescriptorResponse:
    """Retourne le descripteur de génération. Accès vérifié par la couche auth ([read] ou [init])."""  # noqa: E501
    secret = await secrets_repo.get_secret_by_name(conn, wallet_id=wallet_id, name=name)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if not secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "secret_not_placeholder",
                "message": "This secret is not a placeholder; it has no generation descriptor.",
            },
        )

    await audit_log_insert(
        conn,
        "secret.descriptor_accessed",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        target_secret_id=secret.id,
        metadata={"secret_name": name},
    )

    # Reconstruit le GenerationDescriptor validé depuis le dict brut stocké en DB
    descriptor: GenerationDescriptor | None = None
    if secret.generation_descriptor is not None:
        from pydantic import TypeAdapter

        _ta: TypeAdapter[GenerationDescriptor] = TypeAdapter(GenerationDescriptor)
        descriptor = _ta.validate_python(secret.generation_descriptor)

    return DescriptorResponse(
        name=secret.name,
        is_placeholder=secret.is_placeholder,
        generation_descriptor=descriptor,
        generation_version=secret.generation_version,
        linked_secret_id=secret.linked_secret_id,
    )


# ─── By-ID — get / put / delete avec vérif appartenance wallet ────────────────


async def get_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretDetailResponse:
    """Retourne le secret par son UUID. Vérifie qu'il appartient bien au wallet ciblé.

    404 si le secret n'existe pas OU appartient à un autre wallet (ne pas leak l'existence).
    """
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail={
                "error": "placeholder_value_missing",
                "message": "Secret has no value yet, populate it first.",
                "details": {
                    "name": secret.name,
                    "is_placeholder": True,
                    "generation_descriptor": secret.generation_descriptor,
                },
            },
        )

    enc_wallet_key_bytes = await secrets_repo.get_caller_encrypted_wallet_key(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if enc_wallet_key_bytes is None:  # pragma: no cover — grant vérifié juste avant
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "grant_key_missing", "message": "Encrypted wallet key not found"},
        )

    await audit_log_insert(
        conn,
        "secret.read",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        target_secret_id=secret.id,
        metadata={"secret_name": secret.name, "access_via": "by_id"},
    )

    enc_value_b64 = base64.b64encode(secret.encrypted_value or b"").decode()
    enc_key_b64 = base64.b64encode(enc_wallet_key_bytes).decode()

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        encrypted_value=enc_value_b64,
        encrypted_wallet_key=enc_key_b64,
        description=secret.description,
        tags=sorted(secret.tags),
        is_placeholder=secret.is_placeholder,
        generation_version=secret.generation_version,
        type_uuid=secret.type_uuid,
        schema_version_uuid=secret.schema_version_uuid,
    )


async def put_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    req: SecretPutRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretPutResponse:
    """Remplace encrypted_value par UUID. 404 si le secret n'existe pas ou n'appartient pas au wallet."""  # noqa: E501
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "placeholder_expected",
                "message": (
                    "This secret is a placeholder. "
                    "Use POST /populate (permission [init]) to set its value."
                ),
            },
        )

    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — validé par Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    async with conn.transaction():
        new_version = await secrets_repo.update_secret_value(
            conn,
            secret_id=secret.id,
            encrypted_value=enc_value,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={
                "secret_name": secret.name,
                "field": "encrypted_value",
                "access_via": "by_id",
            },
        )

    return SecretPutResponse(generation_version=new_version)


async def delete_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Supprime le secret par UUID. 404 si introuvable ou wallet mismatch."""
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    async with conn.transaction():
        await secrets_repo.delete_secret(conn, secret_id=secret.id)
        await audit_log_insert(
            conn,
            "secret.deleted",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": secret.name, "access_via": "by_id"},
        )


async def patch_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    req: SecretPatchRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Met à jour description/tags par UUID. 404 si secret introuvable ou wallet mismatch."""
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    async with conn.transaction():
        await secrets_repo.update_secret_meta(
            conn,
            secret_id=secret.id,
            description=req.description,
            tags=req.tags,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": secret.name, "field": "metadata", "access_via": "by_id"},
        )


async def populate_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    req: PopulateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> PopulateResponse:
    """Peuple un placeholder par UUID. 404 si secret introuvable ou wallet mismatch."""
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if not secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "secret_already_populated",
                "message": "This secret already has a value. Use PUT to update it.",
            },
        )

    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    descriptor_type = (secret.generation_descriptor or {}).get("type")

    async with conn.transaction():
        new_version = await secrets_repo.populate_secret(
            conn,
            secret_id=secret.id,
            encrypted_value=enc_value,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.populated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={
                "secret_name": secret.name,
                "generator_type": descriptor_type,
                "access_via": "by_id",
            },
        )

    return PopulateResponse(generation_version=new_version)
