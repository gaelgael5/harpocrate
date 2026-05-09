"""Dataclass représentant une ligne de la table users."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
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
    # LOT_57 fix — rsa_priv chiffrée avec recovery_key (pour le flow recovery
    # zero-knowledge). NULL pour les users créés avant migration 022.
    encrypted_rsa_private_key_by_recovery: bytes | None = field(default=None)
    # Colonnes de gouvernance d'identité (LOT_02 — migration 002)
    quarantine_until: datetime.datetime | None = field(default=None)
    quarantine_reason: str | None = field(default=None)
    force_reverify_next_login: bool = field(default=False)
    disabled_at: datetime.datetime | None = field(default=None)
    disabled_reason: str | None = field(default=None)
    # LOT 16 — préférence de locale
    preferred_locale: str = field(default='en')
