"""Modèles de données wallet et API key info du SDK Harpocrate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class WalletInfo:
    """Informations sur un wallet."""

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    valued_secrets_count: int
    placeholder_secrets_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WalletInfo:
        """Construit depuis la réponse JSON de l'API."""
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            description=data.get("description"),
            tags=data.get("tags", []),
            valued_secrets_count=data.get("valued_secrets_count", 0),
            placeholder_secrets_count=data.get("placeholder_secrets_count", 0),
        )


@dataclass(frozen=True)
class ApiKeyInfo:
    """Informations sur l'API key courante (réponse whoami)."""

    api_key_id: UUID
    wallet_id: UUID
    permissions: int
    expires_at: int  # timestamp Unix, 0 = pas d'expiration

    @property
    def permission_names(self) -> list[str]:
        """Noms lisibles des permissions."""
        names = []
        bits = {
            0x01: "read",
            0x02: "write",
            0x04: "add",
            0x08: "remove",
            0x10: "init",
            0x20: "share",
        }
        for bit, name in bits.items():
            if self.permissions & bit:
                names.append(name)
        return names
