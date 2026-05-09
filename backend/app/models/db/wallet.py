"""Dataclasses représentant les lignes des tables wallets / wallet_grants."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class WalletRow:
    """Ligne de la table wallets."""

    id: UUID
    name: str
    description: str | None
    owner_user_id: UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass
class WalletGrantRow:
    """Ligne de la table wallet_grants."""

    id: UUID
    wallet_id: UUID
    grantee_user_id: UUID
    encrypted_wallet_key: bytes
    permissions: int
    granted_by_user_id: UUID
    granted_at: datetime.datetime


@dataclass
class WalletWithGrant:
    """Wallet augmenté du grant du caller + tags + compteurs secrets."""

    id: UUID
    name: str
    description: str | None
    owner_user_id: UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    # Grant du caller
    my_permissions: int

    # Tags
    tags: list[str] = field(default_factory=list)

    # Compteurs (0 jusqu'au LOT_05)
    valued_secrets_count: int = 0
    placeholder_secrets_count: int = 0

    # Suppression logique — None = actif
    deleted_at: datetime.datetime | None = None

    # LOT_58 : environment_id (NULL = "None" virtuel)
    environment_id: UUID | None = None
