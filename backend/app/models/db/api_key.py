"""Modèle DB pour la table api_keys — LOT_08."""
from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel


class ApiKeyRow(BaseModel):
    """Représentation d'une ligne api_keys issue de la DB."""

    id: UUID
    name: str
    description: str | None
    wallet_id: UUID
    owner_user_id: UUID

    auth_hash: bytes
    auth_salt: bytes
    auth_kdf_memory_kb: int
    auth_kdf_iterations: int
    auth_kdf_parallelism: int

    encrypted_wallet_key: bytes
    encrypted_decryption_key_for_owner: bytes

    permissions: int

    expires_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
    created_at: datetime.datetime
