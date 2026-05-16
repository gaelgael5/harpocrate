"""Migration 030 — vérifie que kind='gdrive' est accepté dans remote_backup_connection."""

from __future__ import annotations

import uuid

import asyncpg
import pytest


async def test_kind_gdrive_accepted(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    """Test que 'gdrive' est un kind valide après migration 030."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            inserted = await conn.fetchval(
                """
                INSERT INTO remote_backup_connection
                    (name, kind, config, credentials_encrypted)
                VALUES ($1, $2, '{}'::jsonb, '\\x00'::bytea)
                RETURNING kind
                """,
                f"gdrive-test-{uuid.uuid4()}",
                "gdrive",
            )
            assert inserted == "gdrive"
        finally:
            await tr.rollback()


async def test_kind_unknown_rejected(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    """Test que les kinds inconnus sont toujours rejetés."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO remote_backup_connection
                        (name, kind, config, credentials_encrypted)
                    VALUES ($1, $2, '{}'::jsonb, '\\x00'::bytea)
                    """,
                    f"unknown-test-{uuid.uuid4()}",
                    "dropbox",
                )
        finally:
            await tr.rollback()
