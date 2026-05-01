"""Schémas Pydantic pour export/import de structure wallet — LOT_07."""
from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.models.api.generators import GenerationDescriptor

_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


# ─── Sous-modèles d'export ────────────────────────────────────────────────────


class ExportedWallet(BaseModel):
    """Métadonnées wallet dans le JSON d'export."""

    name: str
    description: str | None = None
    tags: list[str] = []


class ExportedSecret(BaseModel):
    """Un secret dans le JSON d'export — sans valeur chiffrée."""

    name: str
    description: str | None = None
    tags: list[str] = []
    is_placeholder: bool = True
    generation_descriptor: GenerationDescriptor | None = None
    generation_version: int = 1
    linked_secret_name: str | None = None


# ─── Format d'export ─────────────────────────────────────────────────────────


class WalletExport(BaseModel):
    """Payload complet retourné par GET /v1/wallets/{id}/export."""

    format_version: Literal["1"]
    exported_at: datetime | None = None
    exported_from: str | None = None
    wallet: ExportedWallet
    secrets: list[ExportedSecret]

    @model_validator(mode="after")
    def _validate_unique_names(self) -> WalletExport:
        names = [s.name for s in self.secrets]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate secret names in export")
        return self

    @model_validator(mode="after")
    def _validate_linked_names(self) -> WalletExport:
        names = {s.name for s in self.secrets}
        for s in self.secrets:
            if s.linked_secret_name and s.linked_secret_name not in names:
                raise ValueError(
                    f"linked_secret_name '{s.linked_secret_name}' not found in secrets list"
                )
        return self


# ─── Requête d'import ────────────────────────────────────────────────────────


class WalletImportRequest(BaseModel):
    """Corps de POST /v1/wallets/import."""

    format_version: Literal["1"]
    wallet: ExportedWallet
    secrets: list[ExportedSecret] = []
    encrypted_wallet_key_for_owner: str  # base64

    @field_validator("encrypted_wallet_key_for_owner")
    @classmethod
    def _key_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("encrypted_wallet_key_for_owner must not be empty")
        try:
            base64.b64decode(stripped)
        except Exception as exc:
            raise ValueError("encrypted_wallet_key_for_owner must be valid base64") from exc
        return stripped

    @field_validator("secrets", mode="before")
    @classmethod
    def _normalize_secret_tags(cls, v: object) -> object:
        """Normalise les tags des secrets (lowercase + trim) avant validation."""
        if not isinstance(v, list):
            return v
        normalized: list[object] = []
        for item in v:
            if isinstance(item, dict):
                tags = item.get("tags", [])
                if isinstance(tags, list):
                    item = {
                        **item,
                        "tags": [str(t).strip().lower() for t in tags if str(t).strip()],
                    }
            normalized.append(item)
        return normalized

    @field_validator("wallet", mode="before")
    @classmethod
    def _normalize_wallet_tags(cls, v: object) -> object:
        """Normalise les tags du wallet (lowercase + trim) avant validation."""
        if isinstance(v, dict):
            tags = v.get("tags", [])
            if isinstance(tags, list):
                v = {
                    **v,
                    "tags": [str(t).strip().lower() for t in tags if str(t).strip()],
                }
        return v

    @model_validator(mode="after")
    def _validate_unique_names(self) -> WalletImportRequest:
        names = [s.name for s in self.secrets]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate secret names in import payload")
        return self

    @model_validator(mode="after")
    def _validate_linked_names(self) -> WalletImportRequest:
        names = {s.name for s in self.secrets}
        for s in self.secrets:
            if s.linked_secret_name and s.linked_secret_name not in names:
                raise ValueError(
                    f"linked_secret_name '{s.linked_secret_name}' not found in secrets list"
                )
        return self

    @model_validator(mode="after")
    def _validate_secret_names(self) -> WalletImportRequest:
        for s in self.secrets:
            stripped = s.name.strip()
            if not stripped:
                raise ValueError("Secret name must not be empty")
            if len(stripped) > 256:
                raise ValueError(f"Secret name '{stripped}' exceeds 256 characters")
            if not _NAME_RE.match(stripped):
                raise ValueError(
                    f"Secret name '{stripped}' must match ^[A-Za-z0-9_.-]+"
                )
        return self


# ─── Réponse d'import ────────────────────────────────────────────────────────


class WalletImportResponse(BaseModel):
    """Réponse de POST /v1/wallets/import."""

    wallet_id: str  # UUID en string pour serialisation JSON standard
    secrets_created: int
    skipped: list[str] = []
