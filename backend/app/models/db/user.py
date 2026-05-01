"""Dataclass représentant une ligne de la table users."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass
class UserRow:
    """Représentation d'une ligne de la table users."""

    id: UUID
    keycloak_sub: str
    email: str
    display_name: str | None
    rsa_public_key: bytes
    salt_passphrase: bytes
    salt_recovery: bytes
    encrypted_rsa_private_key: bytes
    encrypted_sym_key_by_pass: bytes
    encrypted_sym_key_by_recovery: bytes
    kdf_memory_kb: int
    kdf_iterations: int
    kdf_parallelism: int
    rsa_key_size: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    last_unlock_at: datetime.datetime | None
