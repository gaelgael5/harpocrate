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


def _row_to_backup(row: asyncpg.Record) -> BackupRecord:
    manifest = row["manifest"]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    return BackupRecord(
        id=row["id"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        checksum_sha256=row["checksum_sha256"],
        age_recipient=row["age_recipient"],
        manifest=manifest,
        description=row["description"],
        created_at=row["created_at"],
        created_by_user_id=row["created_by_user_id"],
        imported=row["imported"],
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
) -> BackupRecord:
    row = await conn.fetchrow(
        """
        INSERT INTO backups_local
            (filename, size_bytes, checksum_sha256, age_recipient, manifest,
             description, created_by_user_id, imported)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
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
    )
    assert row is not None
    return _row_to_backup(row)


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
