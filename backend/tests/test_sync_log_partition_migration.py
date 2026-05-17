"""Migration 032 — partitions journalières de sync_log.

Vérifie que les deux fonctions PL/pgSQL existent et se comportent
correctement :
- `ensure_sync_log_partition(target_date)` est idempotent et crée la
  partition au bon nom (`sync_log_YYYY_MM_DD`).
- `drop_old_sync_log_partitions(retention_days)` drop les partitions
  journalières au-delà de la rétention SANS toucher à `sync_log_default`.
"""

from __future__ import annotations

from datetime import date, timedelta

import asyncpg
import pytest


async def _partition_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_inherits
            JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
            JOIN pg_class child ON pg_inherits.inhrelid = child.oid
            WHERE parent.relname = 'sync_log'
              AND child.relname = $1
        )
        """,
        name,
    )


async def test_ensure_sync_log_partition_creates_partition(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Création d'une partition journalière par appel de la fonction."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            target = date(2030, 1, 15)  # date future pour ne pas polluer
            name = await conn.fetchval(
                "SELECT ensure_sync_log_partition($1)", target
            )
            assert name == "sync_log_2030_01_15"
            assert await _partition_exists(conn, "sync_log_2030_01_15")
        finally:
            await tr.rollback()


async def test_ensure_sync_log_partition_is_idempotent(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Deux appels successifs sur la même date ne lèvent pas."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            target = date(2030, 2, 20)
            await conn.execute("SELECT ensure_sync_log_partition($1)", target)
            # Second appel : pas d'erreur
            name = await conn.fetchval(
                "SELECT ensure_sync_log_partition($1)", target
            )
            assert name == "sync_log_2030_02_20"
        finally:
            await tr.rollback()


async def test_drop_old_sync_log_partitions_drops_only_old(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Une partition antérieure à `now - retention_days` est droppée,
    les partitions récentes restent."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            today = date.today()
            old = today - timedelta(days=30)
            recent = today - timedelta(days=2)

            await conn.execute("SELECT ensure_sync_log_partition($1)", old)
            await conn.execute("SELECT ensure_sync_log_partition($1)", recent)

            old_name = f"sync_log_{old.strftime('%Y_%m_%d')}"
            recent_name = f"sync_log_{recent.strftime('%Y_%m_%d')}"

            assert await _partition_exists(conn, old_name)
            assert await _partition_exists(conn, recent_name)

            dropped = await conn.fetchval(
                "SELECT drop_old_sync_log_partitions($1)", 7
            )
            assert dropped >= 1

            assert not await _partition_exists(conn, old_name)
            assert await _partition_exists(conn, recent_name)
        finally:
            await tr.rollback()


async def test_drop_old_sync_log_partitions_never_drops_default(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """`sync_log_default` est la partition catch-all — JAMAIS droppée par
    la fonction de purge (sinon les inserts hors fenêtre cassent)."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            assert await _partition_exists(conn, "sync_log_default")
            await conn.execute("SELECT drop_old_sync_log_partitions($1)", 1)
            assert await _partition_exists(conn, "sync_log_default"), (
                "sync_log_default a été droppée par la fonction de purge — "
                "régression critique du filet de sécurité"
            )
        finally:
            await tr.rollback()


async def test_drop_old_sync_log_partitions_rejects_invalid_retention(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """`retention_days < 1` doit lever une exception (paranoïa)."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            with pytest.raises(asyncpg.RaiseError):
                await conn.execute("SELECT drop_old_sync_log_partitions($1)", 0)
            await tr.rollback()
            tr = conn.transaction()
            await tr.start()
            with pytest.raises(asyncpg.RaiseError):
                await conn.execute("SELECT drop_old_sync_log_partitions($1)", -5)
        finally:
            await tr.rollback()


async def test_partition_routes_insert_to_correct_table(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Un INSERT avec une `occurred_at` dans la fenêtre d'une partition
    journalière atterrit dans cette partition, pas dans `default`."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            target = date(2030, 6, 15)
            await conn.execute("SELECT ensure_sync_log_partition($1)", target)

            await conn.execute(
                """
                INSERT INTO sync_log (
                    emitter_id, type, entity_type, entity_id, operation,
                    payload, is_replication, occurred_at
                )
                VALUES (
                    'test-emitter', 'transaction', 'secrets',
                    '00000000-0000-0000-0000-000000000001',
                    'upsert', '{}'::jsonb, false,
                    '2030-06-15 12:00:00+00'::timestamptz
                )
                """
            )

            in_partition = await conn.fetchval(
                "SELECT COUNT(*) FROM sync_log_2030_06_15"
            )
            in_default = await conn.fetchval(
                "SELECT COUNT(*) FROM sync_log_default "
                "WHERE emitter_id = 'test-emitter' "
                "AND occurred_at = '2030-06-15 12:00:00+00'::timestamptz"
            )
            assert in_partition == 1
            assert in_default == 0
        finally:
            await tr.rollback()
