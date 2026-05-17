"""Scheduler de partitions journalières — `sync_log_partition_scheduler`.

Tests unitaires + intégration légère :
- `ensure_partitions_window` crée today + days_ahead jours.
- `drop_old_partitions` délègue à la fonction PL/pgSQL.
- `start` / `stop` du scheduler ne plantent pas et créent un tick initial.
"""

from __future__ import annotations

import base64
import os

# Settings env vars (mêmes valeurs que conftest._initialize_settings_singleton)
# — nécessaires AVANT l'import de `app.services.sync_log_partition_scheduler`,
# qui importe `app.core.config.settings` à module load. Le fixture autouse
# session du conftest ne tourne qu'au début des tests, donc trop tard pour
# l'import à la collection.
os.environ.setdefault("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
os.environ.setdefault("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
os.environ.setdefault("HARPOCRATE_KEYCLOAK_REALM", "yoops")
os.environ.setdefault("HARPOCRATE_KEYCLOAK_CLIENT_ID", "harpocrate-vault")
os.environ.setdefault("HARPOCRATE_HMAC_KEY", base64.b64encode(b"k" * 32).decode())
os.environ.setdefault("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from app.services import sync_log_partition_scheduler as scheduler_svc


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


async def test_ensure_partitions_window_creates_today_and_tomorrow(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            today = datetime.now(UTC).date()
            tomorrow = today + timedelta(days=1)

            names = await scheduler_svc.ensure_partitions_window(
                conn, days_ahead=1
            )

            assert len(names) == 2
            assert f"sync_log_{today.strftime('%Y_%m_%d')}" in names
            assert f"sync_log_{tomorrow.strftime('%Y_%m_%d')}" in names

            for name in names:
                assert await _partition_exists(conn, name)
        finally:
            await tr.rollback()


async def test_ensure_partitions_window_days_ahead_zero(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """`days_ahead=0` ne crée que la partition d'aujourd'hui."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            names = await scheduler_svc.ensure_partitions_window(
                conn, days_ahead=0
            )
            assert len(names) == 1
        finally:
            await tr.rollback()


async def test_ensure_partitions_window_rejects_negative(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(ValueError, match="days_ahead must be >= 0"):
            await scheduler_svc.ensure_partitions_window(conn, days_ahead=-1)


async def test_drop_old_partitions_returns_count(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Crée des partitions vieilles, drop avec retention courte, compte."""
    from datetime import date

    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            today = date.today()
            for offset in (60, 50, 40):
                target = today - timedelta(days=offset)
                await conn.execute(
                    "SELECT ensure_sync_log_partition($1)", target
                )
            count = await scheduler_svc.drop_old_partitions(conn, retention_days=30)
            assert count >= 3
        finally:
            await tr.rollback()


async def test_scheduler_start_creates_initial_partitions(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`start()` exécute un tick initial : aujourd'hui+demain sont créés."""

    async def fake_get_pool() -> asyncpg.Pool[asyncpg.Record]:
        return real_db_pool

    monkeypatch.setattr(
        scheduler_svc.SyncLogPartitionScheduler, "_get_pool", staticmethod(fake_get_pool)
    )

    scheduler = scheduler_svc.SyncLogPartitionScheduler(interval_seconds=3600)
    try:
        await scheduler.start()

        async with real_db_pool.acquire() as conn:
            today = datetime.now(UTC).date()
            tomorrow = today + timedelta(days=1)
            assert await _partition_exists(
                conn, f"sync_log_{today.strftime('%Y_%m_%d')}"
            )
            assert await _partition_exists(
                conn, f"sync_log_{tomorrow.strftime('%Y_%m_%d')}"
            )
    finally:
        await scheduler.stop()


async def test_scheduler_stop_is_idempotent(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`stop()` peut être appelé deux fois sans plantage."""

    async def fake_get_pool() -> asyncpg.Pool[asyncpg.Record]:
        return real_db_pool

    monkeypatch.setattr(
        scheduler_svc.SyncLogPartitionScheduler, "_get_pool", staticmethod(fake_get_pool)
    )

    scheduler = scheduler_svc.SyncLogPartitionScheduler(interval_seconds=3600)
    await scheduler.start()
    await scheduler.stop()
    await scheduler.stop()  # second call : no-op


async def test_scheduler_tick_logs_when_partitions_dropped(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un tick après ajout de partitions anciennes les drop bien."""
    from datetime import date

    async def fake_get_pool() -> asyncpg.Pool[asyncpg.Record]:
        return real_db_pool

    monkeypatch.setattr(
        scheduler_svc.SyncLogPartitionScheduler, "_get_pool", staticmethod(fake_get_pool)
    )

    scheduler = scheduler_svc.SyncLogPartitionScheduler(interval_seconds=3600)
    try:
        async with real_db_pool.acquire() as conn:
            old_target = date.today() - timedelta(days=60)
            await conn.execute(
                "SELECT ensure_sync_log_partition($1)", old_target
            )
            assert await _partition_exists(
                conn, f"sync_log_{old_target.strftime('%Y_%m_%d')}"
            )

        await scheduler.start()

        async with real_db_pool.acquire() as conn:
            assert not await _partition_exists(
                conn, f"sync_log_{old_target.strftime('%Y_%m_%d')}"
            )
    finally:
        await scheduler.stop()


async def test_init_scheduler_returns_singleton() -> None:
    """`init_scheduler()` retourne toujours la même instance."""
    s1 = scheduler_svc.init_scheduler()
    s2 = scheduler_svc.init_scheduler()
    assert s1 is s2
