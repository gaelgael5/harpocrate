"""Schémas Pydantic pour les endpoints /v1/wallets/{id}/grants — LOT_04."""
from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

_MAX_ENCRYPTED_KEY_BYTES = 1024  # RSA-4096 OAEP = 512 bytes max en pratique


class CreateGrantRequest(BaseModel):
    """Corps de POST /v1/wallets/{id}/grants."""

    grantee_user_id: UUID
    encrypted_wallet_key_for_grantee: str  # base64
    permissions: int

    @field_validator("permissions")
    @classmethod
    def _perms_range(cls, v: int) -> int:
        if not (1 <= v <= 63):
            raise ValueError("permissions must be in [1, 63]")
        return v

    @field_validator("encrypted_wallet_key_for_grantee")
    @classmethod
    def _key_not_empty(cls, v: str) -> str:
        import base64

        stripped = v.strip()
        if not stripped:
            raise ValueError("encrypted_wallet_key_for_grantee must not be empty")
        try:
            decoded = base64.b64decode(stripped)
        except Exception as exc:
            raise ValueError("encrypted_wallet_key_for_grantee must be valid base64") from exc
        if len(decoded) > _MAX_ENCRYPTED_KEY_BYTES:
            raise ValueError(
                f"encrypted_wallet_key_for_grantee exceeds {_MAX_ENCRYPTED_KEY_BYTES} bytes"
            )
        return stripped


class UpdateGrantRequest(BaseModel):
    """Corps de PATCH /v1/wallets/{id}/grants/{grant_id}."""

    permissions: int
    encrypted_wallet_key_for_grantee: str | None = None

    @field_validator("permissions")
    @classmethod
    def _perms_range(cls, v: int) -> int:
        if not (1 <= v <= 63):
            raise ValueError("permissions must be in [1, 63]")
        return v

    @field_validator("encrypted_wallet_key_for_grantee")
    @classmethod
    def _key_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        import base64

        stripped = v.strip()
        if not stripped:
            raise ValueError("encrypted_wallet_key_for_grantee must not be empty if provided")
        try:
            decoded = base64.b64decode(stripped)
        except Exception as exc:
            raise ValueError("encrypted_wallet_key_for_grantee must be valid base64") from exc
        if len(decoded) > _MAX_ENCRYPTED_KEY_BYTES:
            raise ValueError(
                f"encrypted_wallet_key_for_grantee exceeds {_MAX_ENCRYPTED_KEY_BYTES} bytes"
            )
        return stripped


class GrantItem(BaseModel):
    """Un grant dans la liste."""

    id: UUID
    grantee_user_id: UUID
    grantee_email: str
    grantee_display_name: str | None
    permissions: int
    is_owner: bool
    granted_by_user_id: UUID
    granted_at: datetime.datetime


class GrantListResponse(BaseModel):
    """Réponse de GET /v1/wallets/{id}/grants."""

    grants: list[GrantItem]


class GrantCreateResponse(BaseModel):
    """Réponse de POST /v1/wallets/{id}/grants."""

    grant_id: UUID


class MyGrantResponse(BaseModel):
    """Réponse de GET /v1/wallets/{id}/my-grant."""

    id: UUID
    permissions: int
    encrypted_wallet_key: str  # base64
    is_owner: bool
