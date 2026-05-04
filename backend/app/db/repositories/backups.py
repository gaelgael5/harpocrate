"""Repository pour la table backups_local — LOT_12A."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


@dataclass
class BackupRecord:
    id: UUID
    filename: str
    size_bytes: int
    checksum_sha256: str
    age_recipient: str
    manifest: dict[str, Any]
    description: str | None
    created_at: datetime
    created_by_user_id: UUID | None
    imported: bool
    tier: str | None = None
    promoted_from_id: UUID | None = None


def _row_to_backup(row: asyncpg.Record) -> BackupRecord:
    manifest = row["manifest"]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    cols = dict(row)
    return BackupRecord(
        id=cols["id"],
        filename=cols["filename"],
        size_bytes=cols["size_bytes"],
        checksum_sha256=cols["checksum_sha256"],
        age_recipient=cols["age_recipient"],
        manifest=manifest,
        description=cols["description"],
        created_at=cols["created_at"],
        created_by_user_id=cols["created_by_user_id"],
        imported=cols["imported"],
        tier=cols.get("tier"),
        promoted_from_id=cols.get("promoted_from_id"),
    )


async def insert_backup(
    conn: asyncpg.Connection,
    *,
    filename: str,
    size_bytes: int,
    checksum_sha256: str,
    age_recipient: str,
    manifest: dict[str, Any],
    description: str | None,
    created_by_user_id: UUID | None,
    imported: bool = False,
    tier: str | None = None,
    promoted_from_id: UUID | None = None,
) -> BackupRecord:
    row = await conn.fetchrow(
        """
        INSERT INTO backups_local
            (filename, size_bytes, checksum_sha256, age_recipient, manifest,
             description, created_by_user_id, imported, tier, promoted_from_id)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
        RETURNING *
        """,
        filename,
        size_bytes,
        checksum_sha256,
        age_recipient,
        json.dumps(manifest),
        description,
        created_by_user_id,
        imported,
        tier,
        promoted_from_id,
    )
    assert row is not None
    return _row_to_backup(row)


async def set_backup_tier(
    conn: asyncpg.Connection,
    backup_id: UUID,
    tier: str,
    promoted_from_id: UUID | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE backups_local SET tier = $1, promoted_from_id = $2
        WHERE id = $3
        """,
        tier, promoted_from_id, backup_id,
    )


async def list_snapshots(
    conn: asyncpg.Connection,
    *,
    tier: str | None = None,
    limit: int = 100,
) -> list[BackupRecord]:
    if tier is not None:
        rows = await conn.fetch(
            """
            SELECT * FROM backups_local
            WHERE filename LIKE 'harpocrate-snapshot-%' AND tier = $1
            ORDER BY created_at DESC LIMIT $2
            """,
            tier, limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT * FROM backups_local
            WHERE filename LIKE 'harpocrate-snapshot-%'
            ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
    return [_row_to_backup(r) for r in rows]


async def list_backups(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[BackupRecord]:
    if cursor_created_at is not None and cursor_id is not None:
        rows = await conn.fetch(
            """
            SELECT * FROM backups_local
            WHERE (created_at, id) < ($1, $2)
            ORDER BY created_at DESC, id DESC
            LIMIT $3
            """,
            cursor_created_at, cursor_id, limit,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM backups_local ORDER BY created_at DESC, id DESC LIMIT $1",
            limit,
        )
    return [_row_to_backup(r) for r in rows]


async def get_backup(conn: asyncpg.Connection, backup_id: UUID) -> BackupRecord | None:
    row = await conn.fetchrow(
        "SELECT * FROM backups_local WHERE id = $1", backup_id
    )
    return _row_to_backup(row) if row else None


async def delete_backup(conn: asyncpg.Connection, backup_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM backups_local WHERE id = $1", backup_id
    )
    return result == "DELETE 1"
