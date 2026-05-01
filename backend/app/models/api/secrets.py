"""Schémas Pydantic pour les endpoints /v1/wallets/{id}/secrets/* — LOT_05."""
from __future__ import annotations

import base64
import re
from uuid import UUID

from pydantic import BaseModel, field_validator

# Limite : 5 MB après décodage base64
_MAX_VALUE_BYTES = 5 * 1024 * 1024

# Regex env-var-safe
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


# ─── Requêtes ─────────────────────────────────────────────────────────────────


class SecretCreateRequest(BaseModel):
    """Corps de POST /v1/wallets/{id}/secrets."""

    name: str
    description: str | None = None
    tags: list[str] = []
    encrypted_value: str  # base64

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        if len(stripped) > 256:
            raise ValueError("name must not exceed 256 characters")
        if not _NAME_RE.match(stripped):
            raise ValueError(
                "name must match ^[A-Za-z0-9_.-]+ (env-var-safe characters only)"
            )
        return stripped

    @field_validator("description")
    @classmethod
    def _desc_valid(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("description must not exceed 1000 characters")
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_normalize(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("tags must be a list")
        return [str(t).strip().lower() for t in v if str(t).strip()]

    @field_validator("encrypted_value")
    @classmethod
    def _value_valid(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("encrypted_value must not be empty")
        try:
            raw = base64.b64decode(v)
        except Exception as exc:
            raise ValueError("encrypted_value must be valid base64") from exc
        if len(raw) > _MAX_VALUE_BYTES:
            raise ValueError(
                f"encrypted_value exceeds max size of {_MAX_VALUE_BYTES} bytes after decoding"
            )
        return v


class SecretPutRequest(BaseModel):
    """Corps de PUT /v1/wallets/{id}/secrets/{name} — mise à jour valeur."""

    encrypted_value: str  # base64

    @field_validator("encrypted_value")
    @classmethod
    def _value_valid(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("encrypted_value must not be empty")
        try:
            raw = base64.b64decode(v)
        except Exception as exc:
            raise ValueError("encrypted_value must be valid base64") from exc
        if len(raw) > _MAX_VALUE_BYTES:
            raise ValueError(
                f"encrypted_value exceeds max size of {_MAX_VALUE_BYTES} bytes after decoding"
            )
        return v


class SecretPatchRequest(BaseModel):
    """Corps de PATCH /v1/wallets/{id}/secrets/{name} — métadonnées uniquement."""

    description: str | None = None
    tags: list[str] | None = None

    @field_validator("description")
    @classmethod
    def _desc_valid(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("description must not exceed 1000 characters")
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_normalize(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("tags must be a list")
        return [str(t).strip().lower() for t in v if str(t).strip()]


# ─── Réponses ─────────────────────────────────────────────────────────────────


class _CallerRef(BaseModel):
    type: str
    id: UUID


class SecretListItem(BaseModel):
    """Item dans la liste GET /v1/wallets/{id}/secrets — sans encrypted_value."""

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    is_placeholder: bool
    generation_version: int
    linked_secret_id: UUID | None
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    created_by: _CallerRef | None
    updated_by: _CallerRef | None


class SecretListResponse(BaseModel):
    """Réponse de GET /v1/wallets/{id}/secrets."""

    secrets: list[SecretListItem]
    next_cursor: str | None


class SecretDetailResponse(BaseModel):
    """Réponse de GET /v1/wallets/{id}/secrets/{name}."""

    id: UUID
    name: str
    encrypted_value: str  # base64
    encrypted_wallet_key: str  # base64 — clé du caller depuis wallet_grants
    description: str | None
    tags: list[str]
    is_placeholder: bool
    generation_version: int


class SecretCreateResponse(BaseModel):
    """Réponse de POST /v1/wallets/{id}/secrets."""

    secret_id: UUID


class SecretPutResponse(BaseModel):
    """Réponse de PUT /v1/wallets/{id}/secrets/{name}."""

    generation_version: int
