"""Modèles SDK pour le catalogue de types de secrets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class SchemaVersion:
    """Version d'un schéma de type de secret."""

    version_uuid: UUID
    version: int
    schema_data: dict[str, Any]
    schema_ui: dict[str, Any]
    created_at: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SchemaVersion:
        return SchemaVersion(
            version_uuid=UUID(d["version_uuid"]),
            version=int(d["version"]),
            schema_data=dict(d.get("schema_data") or {}),
            schema_ui=dict(d.get("schema_ui") or {}),
            created_at=d.get("created_at"),
        )


@dataclass(frozen=True)
class SecretType:
    """Type de secret (avec sa version courante)."""

    type_uuid: UUID
    type: str
    sous_type: str
    label: str | None
    description: str | None
    is_system: bool
    deprecated_at: str | None
    current_version: SchemaVersion | None
    used_by_secrets_count: int = 0
    all_versions: list[SchemaVersion] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SecretType:
        cv_full = d.get("current_version_full")
        cv = SchemaVersion.from_dict(cv_full) if cv_full else None
        # Le list endpoint renvoie une forme courte 'current_version' ;
        # le detail endpoint renvoie 'current_version_full' avec les schémas.
        if cv is None and d.get("current_version"):
            short = d["current_version"]
            cv = SchemaVersion(
                version_uuid=UUID(short["version_uuid"]),
                version=int(short["version"]),
                schema_data={},
                schema_ui={},
                created_at=short.get("created_at"),
            )
        all_versions = [SchemaVersion.from_dict(v) for v in d.get("all_versions", [])]
        return SecretType(
            type_uuid=UUID(d["type_uuid"]),
            type=str(d["type"]),
            sous_type=str(d["sous_type"]),
            label=d.get("label"),
            description=d.get("description"),
            is_system=bool(d.get("is_system", False)),
            deprecated_at=d.get("deprecated_at"),
            current_version=cv,
            used_by_secrets_count=int(d.get("used_by_secrets_count", 0)),
            all_versions=all_versions,
        )
