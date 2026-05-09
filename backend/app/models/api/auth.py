"""Schemas Pydantic pour les endpoints /me/* (LOT_02)."""
from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

# ─── Paramètres KDF ──────────────────────────────────────────────────────────


class KdfParams(BaseModel):
    memory_kb: int
    iterations: int
    parallelism: int


# ─── Requêtes ────────────────────────────────────────────────────────────────


class BootstrapRequest(BaseModel):
    """Corps de POST /v1/me/bootstrap."""

    rsa_public_key: str  # base64
    salt_passphrase: str  # base64, exactement 16 bytes décodés
    salt_recovery: str  # base64, exactement 16 bytes décodés
    encrypted_rsa_private_key: str  # base64
    encrypted_sym_key_by_pass: str  # base64
    encrypted_sym_key_by_recovery: str  # base64
    # LOT_57 fix : rsa_priv re-chiffrée avec recovery_key, indispensable
    # pour rendre le flow recovery (24 mots) opérant.
    encrypted_rsa_private_key_by_recovery: str  # base64

    kdf_memory_kb: int
    kdf_iterations: int
    kdf_parallelism: int
    rsa_key_size: int

    @field_validator(
        "rsa_public_key",
        "encrypted_rsa_private_key",
        "encrypted_sym_key_by_pass",
        "encrypted_sym_key_by_recovery",
        "encrypted_rsa_private_key_by_recovery",
    )
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty")
        return v


class PassphraseChangeRequest(BaseModel):
    """Corps de PUT /v1/me/passphrase."""

    new_salt_passphrase: str  # base64, exactement 16 bytes décodés
    new_encrypted_rsa_private_key: str  # base64
    new_encrypted_sym_key_by_pass: str  # base64

    kdf_memory_kb: int
    kdf_iterations: int
    kdf_parallelism: int


class RecoveryRenewRequest(BaseModel):
    """Corps de PUT /v1/me/recovery."""

    new_salt_recovery: str  # base64, exactement 16 bytes décodés
    new_encrypted_sym_key_by_recovery: str  # base64
    # LOT_57 fix : nouvelle recovery_key → re-chiffrement obligatoire de
    # rsa_priv avec cette nouvelle clé, sinon le flow recovery casserait.
    new_encrypted_rsa_private_key_by_recovery: str  # base64


# ─── Réponses ────────────────────────────────────────────────────────────────


class BootstrapResponse(BaseModel):
    user_id: UUID


class MeResponse(BaseModel):
    id: UUID
    keycloak_sub: str
    email: str
    display_name: str | None
    has_bootstrap: bool
    kdf_params: KdfParams
    rsa_key_size: int
    created_at: datetime.datetime
    last_unlock_at: datetime.datetime | None
    preferred_locale: str = 'en'


class CryptoResponse(BaseModel):
    salt_passphrase: str  # base64
    encrypted_rsa_private_key: str  # base64
    encrypted_sym_key_by_pass: str  # base64
    kdf_params: KdfParams
    rsa_public_key: str  # base64


class RecoveryCryptoResponse(BaseModel):
    salt_recovery: str  # base64
    encrypted_sym_key_by_recovery: str  # base64


class UpdatedAtResponse(BaseModel):
    updated_at: datetime.datetime
