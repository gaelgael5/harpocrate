"""Migration 031 — vérifie que la table oauth_pending_session est créée correctement."""

from __future__ import annotations

import asyncpg
import pytest

_EXPECTED_COLUMNS = [
    "id",
    "state",
    "provider",
    "payload",
    "result",
    "status",
    "target_connection_id",
    "created_by_user_id",
    "created_at",
    "expires_at",
]


async def test_oauth_pending_session_columns(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'oauth_pending_session' "
            "ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for expected in _EXPECTED_COLUMNS:
        assert expected in names, f"colonne manquante : {expected}"


async def test_oauth_pending_session_state_unique(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Le state DOIT être UNIQUE (protection replay)."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(
                """
                INSERT INTO oauth_pending_session
                    (state, provider, payload, expires_at)
                VALUES ('s1', 'gdrive', '{}'::jsonb, NOW() + INTERVAL '10 minutes')
                """
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    """
                    INSERT INTO oauth_pending_session
                        (state, provider, payload, expires_at)
                    VALUES ('s1', 'gdrive', '{}'::jsonb, NOW() + INTERVAL '10 minutes')
                    """
                )
        finally:
            await tr.rollback()


async def test_oauth_pending_session_provider_check(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO oauth_pending_session
                        (state, provider, payload, expires_at)
                    VALUES ('s2', 'dropbox', '{}'::jsonb, NOW() + INTERVAL '10 minutes')
                    """
                )
        finally:
            await tr.rollback()


async def test_oauth_pending_session_status_check(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO oauth_pending_session
                        (state, provider, payload, status, expires_at)
                    VALUES ('s3', 'gdrive', '{}'::jsonb, 'consumed', NOW() + INTERVAL '10 minutes')
                    """
                )
        finally:
            await tr.rollback()
