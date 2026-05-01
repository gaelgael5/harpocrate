"""Dataclass représentant une ligne de la table secrets."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class SecretRow:
    """Ligne de la table secrets telle que retournée par le repo."""

    id: UUID
    wallet_id: UUID
    name: str
    description: str | None
    encrypted_value: bytes | None
    is_placeholder: bool
    generation_version: int
    linked_secret_id: UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    created_by_user_id: UUID | None
    created_by_api_key_id: UUID | None
    updated_by_user_id: UUID | None
    updated_by_api_key_id: UUID | None
    tags: list[str] = field(default_factory=list)
    # JSONB brut décodé par asyncpg en dict Python (None si secret valorisé)
    generation_descriptor: dict[str, Any] | None = None
