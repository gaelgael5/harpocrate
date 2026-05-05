"""Modèles de données secrets du SDK Harpocrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class SecretInfo:
    """Métadonnées d'un secret (sans valeur chiffrée)."""

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    is_placeholder: bool
    generation_version: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretInfo:
        """Construit depuis la réponse JSON de l'API."""
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            description=data.get("description"),
            tags=data.get("tags", []),
            is_placeholder=data.get("is_placeholder", False),
            generation_version=data.get("generation_version", 1),
        )


@dataclass(frozen=True)
class SecretDetail:
    """Détail d'un secret avec blobs chiffrés (réponse GET /{name})."""

    id: UUID
    name: str
    encrypted_value_b64: str
    encrypted_wallet_key_b64: str
    description: str | None
    tags: list[str]
    is_placeholder: bool
    generation_version: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretDetail:
        """Construit depuis la réponse JSON de l'API."""
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            encrypted_value_b64=data["encrypted_value"],
            encrypted_wallet_key_b64=data["encrypted_wallet_key"],
            description=data.get("description"),
            tags=data.get("tags", []),
            is_placeholder=data.get("is_placeholder", False),
            generation_version=data.get("generation_version", 1),
        )


@dataclass(frozen=True)
class PopulateResult:
    """Résultat d'une opération populate."""

    name: str
    success: bool
    error: str | None = None
    generation_version: int = 0

    @classmethod
    def ok(cls, name: str, version: int = 0) -> PopulateResult:
        """Construit un résultat de succès."""
        return cls(name=name, success=True, generation_version=version)

    @classmethod
    def failed(cls, name: str, error: str) -> PopulateResult:
        """Construit un résultat d'échec."""
        return cls(name=name, success=False, error=error)


@dataclass
class SecretListResponse:
    """Réponse de list_secrets avec pagination."""

    secrets: list[SecretInfo] = field(default_factory=list)
    next_cursor: str | None = None
