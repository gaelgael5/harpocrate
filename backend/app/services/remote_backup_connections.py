"""Service métier — connexions de backup distantes (CRUD + chiffrement transparent).

Le service garantit que les credentials sont :
  - chiffrés avant insertion en BDD
  - jamais retournés en clair par les méthodes `list_*` ou `get_*` (pour éviter les fuites
    via les endpoints publics même si un dev oublie de filtrer)
  - déchiffrés uniquement par `get_decrypted_credentials()` (utilisé par les providers
    pour ouvrir une connexion réelle)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.db.repositories import remote_backup_connections as repo
from app.services import remote_backup_crypto as crypto


@dataclass(frozen=True)
class RemoteBackupConnection:
    """DTO côté service — credentials JAMAIS exposés en clair ici."""

    id: UUID
    name: str
    kind: str
    config: dict[str, Any]
    created_at: str
    updated_at: str
    created_by_user_id: UUID | None
    deleted_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "kind": self.kind,
            "config": self.config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by_user_id": str(self.created_by_user_id) if self.created_by_user_id else None,
            "deleted_at": self.deleted_at,
        }


def _row_to_dto(row: asyncpg.Record) -> RemoteBackupConnection:
    raw_config = row["config"]
    if isinstance(raw_config, str):
        config = json.loads(raw_config)
    else:
        config = dict(raw_config) if raw_config else {}
    return RemoteBackupConnection(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        config=config,
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
        created_by_user_id=row["created_by_user_id"],
        deleted_at=row["deleted_at"].isoformat() if row["deleted_at"] else None,
    )


# ─── Lecture ──────────────────────────────────────────────────────────────────


async def list_connections(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[RemoteBackupConnection]:
    rows = await repo.list_active(conn)
    return [_row_to_dto(r) for r in rows]


async def get_connection(
    conn: asyncpg.Connection[asyncpg.Record],
    connection_id: UUID,
) -> RemoteBackupConnection | None:
    row = await repo.get_by_id(conn, connection_id)
    if row is None or row["deleted_at"] is not None:
        return None
    return _row_to_dto(row)


async def get_decrypted_credentials(
    conn: asyncpg.Connection[asyncpg.Record],
    connection_id: UUID,
) -> dict[str, Any] | None:
    """Retourne les credentials en clair pour ouvrir une connexion vers le serveur distant.

    À n'utiliser QUE par les providers au moment d'établir la connexion réseau,
    JAMAIS dans une réponse HTTP.
    """
    row = await repo.get_by_id(conn, connection_id)
    if row is None or row["deleted_at"] is not None:
        return None
    blob = bytes(row["credentials_encrypted"])
    return crypto.decrypt_credentials(blob)


# ─── Écriture ─────────────────────────────────────────────────────────────────


async def create_connection(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    name: str,
    kind: str,
    config: dict[str, Any],
    credentials: dict[str, Any],
    created_by_user_id: UUID | None,
) -> UUID:
    """Crée une nouvelle connexion. Chiffre les credentials avant insertion."""
    encrypted = crypto.encrypt_credentials(credentials)
    return await repo.insert(
        conn,
        name=name,
        kind=kind,
        config=config,
        credentials_encrypted=encrypted,
        created_by_user_id=created_by_user_id,
    )


async def update_connection(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    connection_id: UUID,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
) -> int:
    """Update partiel. Si `credentials` fourni, le re-chiffre. Retourne nb de rows affectées."""
    encrypted: bytes | None = None
    if credentials is not None:
        encrypted = crypto.encrypt_credentials(credentials)
    return await repo.update(
        conn,
        connection_id=connection_id,
        name=name,
        config=config,
        credentials_encrypted=encrypted,
    )


async def delete_connection(
    conn: asyncpg.Connection[asyncpg.Record],
    connection_id: UUID,
) -> int:
    return await repo.soft_delete(conn, connection_id)
