"""Schémas Pydantic pour les endpoints /v1/wallets/{id}/api-keys/* — LOT_08."""
from __future__ import annotations

import base64
import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.core.config import settings

# ─── KDF floor constants ─────────────────────────────────────────────────────

_AUTH_SALT_BYTES = 16


# ─── Requêtes ─────────────────────────────────────────────────────────────────


class ApiKeyCreateRequest(BaseModel):
    """Corps de POST /v1/wallets/{id}/api-keys."""

    name: str
    description: str | None = None
    permissions: int
    expires_at: datetime.datetime | None = None

    # Argon2id hash du auth_secret (calculé côté client)
    auth_secret: str           # base64url — envoyé une seule fois, jamais stocké
    auth_hash: str             # base64 — stocké en DB
    auth_salt: str             # base64 16 bytes
    auth_kdf_memory_kb: int
    auth_kdf_iterations: int
    auth_kdf_parallelism: int

    # Chiffrement de la wallet_key via la decryption_key de l'API key
    encrypted_wallet_key: str                    # base64
    # Chiffrement de la decryption_key pour que l'owner puisse la récupérer
    encrypted_decryption_key_for_owner: str      # base64
    # decryption_key en clair — jamais stocké en DB, sert uniquement au HMAC
    decryption_key: str                          # base64url — inclus dans le token

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        if len(stripped) > 256:
            raise ValueError("name must not exceed 256 characters")
        return stripped

    @field_validator("description")
    @classmethod
    def _desc_valid(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("description must not exceed 1000 characters")
        return v

    @field_validator("permissions")
    @classmethod
    def _perms_valid(cls, v: int) -> int:
        if v <= 0 or v > 0x3F:
            raise ValueError("permissions must be between 1 and 63")
        return v

    @field_validator("expires_at")
    @classmethod
    def _expires_future(cls, v: datetime.datetime | None) -> datetime.datetime | None:
        if v is not None:
            now = datetime.datetime.now(tz=datetime.UTC)
            if v <= now:
                raise ValueError("expires_at must be in the future")
        return v

    @field_validator("auth_salt")
    @classmethod
    def _salt_valid(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except Exception as exc:
            raise ValueError("auth_salt must be valid base64") from exc
        if len(raw) != _AUTH_SALT_BYTES:
            raise ValueError(f"auth_salt must be exactly {_AUTH_SALT_BYTES} bytes when decoded")
        return v

    @field_validator("auth_kdf_memory_kb")
    @classmethod
    def _kdf_memory_floor(cls, v: int) -> int:
        floor = settings.kdf_memory_kb
        if v < floor:
            raise ValueError(f"auth_kdf_memory_kb must be >= {floor}")
        return v

    @field_validator("auth_kdf_iterations")
    @classmethod
    def _kdf_iterations_floor(cls, v: int) -> int:
        floor = settings.kdf_iterations
        if v < floor:
            raise ValueError(f"auth_kdf_iterations must be >= {floor}")
        return v

    @field_validator("auth_kdf_parallelism")
    @classmethod
    def _kdf_parallelism_floor(cls, v: int) -> int:
        floor = settings.kdf_parallelism
        if v < floor:
            raise ValueError(f"auth_kdf_parallelism must be >= {floor}")
        return v

    @field_validator("auth_hash", "auth_secret", "encrypted_wallet_key",
                     "encrypted_decryption_key_for_owner", "decryption_key")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be empty")
        return v


class ApiKeyPatchRequest(BaseModel):
    """Corps de PATCH /v1/wallets/{id}/api-keys/{key_id} — métadonnées uniquement."""

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("name must not be empty")
            if len(stripped) > 256:
                raise ValueError("name must not exceed 256 characters")
            return stripped
        return v

    @field_validator("description")
    @classmethod
    def _desc_valid(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("description must not exceed 1000 characters")
        return v


# ─── Réponses ─────────────────────────────────────────────────────────────────


class ApiKeyCreateResponse(BaseModel):
    """Réponse de POST /v1/wallets/{id}/api-keys — token affiché une seule fois."""

    api_key_id: UUID
    token: str  # hrpv_1_... complet, jamais re-montré


class ApiKeyItem(BaseModel):
    """Item dans GET /v1/wallets/{id}/api-keys — métadonnées uniquement."""

    id: UUID
    name: str
    description: str | None
    owner_user_id: UUID
    permissions: int
    expires_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
    created_at: datetime.datetime


class ApiKeyListResponse(BaseModel):
    """Réponse de GET /v1/wallets/{id}/api-keys."""

    api_keys: list[ApiKeyItem]
