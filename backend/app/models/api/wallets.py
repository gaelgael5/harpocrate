"""Schémas Pydantic pour les endpoints /v1/wallets/* et /v1/users/lookup (LOT_03)."""
from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

# ─── Requêtes ─────────────────────────────────────────────────────────────────


class WalletCreateRequest(BaseModel):
    """Corps de POST /v1/wallets."""

    name: str
    description: str | None = None
    tags: list[str] = []
    encrypted_wallet_key_for_owner: str  # base64

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        if len(stripped) > 255:
            raise ValueError("name must not exceed 255 characters")
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

    @field_validator("encrypted_wallet_key_for_owner")
    @classmethod
    def _key_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("encrypted_wallet_key_for_owner must not be empty")
        return v


class WalletPatchRequest(BaseModel):
    """Corps de PATCH /v1/wallets/{id}."""

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        if len(stripped) > 255:
            raise ValueError("name must not exceed 255 characters")
        return stripped

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


class TransferOwnershipRequest(BaseModel):
    """Corps de POST /v1/wallets/{id}/transfer-ownership."""

    new_owner_user_id: UUID


# ─── Réponses ─────────────────────────────────────────────────────────────────


class WalletItem(BaseModel):
    """Wallet dans la liste ou en réponse de GET/PATCH."""

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    owner_user_id: UUID
    is_owner: bool
    my_permissions: int
    valued_secrets_count: int
    placeholder_secrets_count: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None = None


class WalletListResponse(BaseModel):
    """Réponse de GET /v1/wallets."""

    wallets: list[WalletItem]
    next_cursor: str | None
    deleted_wallets: list[WalletItem] = []


class WalletCreateResponse(BaseModel):
    """Réponse de POST /v1/wallets."""

    wallet_id: UUID


class UserLookupResponse(BaseModel):
    """Réponse de GET /v1/users/lookup."""

    user_id: UUID
    email: str
    display_name: str | None
    rsa_public_key: str  # base64
