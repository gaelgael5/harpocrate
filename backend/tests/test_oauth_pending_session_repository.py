"""Tests du repository oauth_pending_session."""

from __future__ import annotations

import asyncpg

from app.db.repositories import oauth_pending_session as repo


async def test_insert_and_get_by_state(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            sid = await repo.insert(
                conn,
                state="state-aaa",
                provider="gdrive",
                payload={"client_id": "abc", "folder_name": "Backups"},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            assert sid is not None
            row = await repo.get_by_state(conn, "state-aaa")
            assert row is not None
            assert row["status"] == "pending"
            assert row["provider"] == "gdrive"
        finally:
            await tr.rollback()


async def test_get_active_by_state_expired_returns_none(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await repo.insert(
                conn,
                state="state-old",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=-60,
            )
            row = await repo.get_active_by_state(conn, "state-old")
            assert row is None
        finally:
            await tr.rollback()


async def test_mark_authorized(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await repo.insert(
                conn,
                state="state-bbb",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            await repo.mark_authorized(
                conn,
                state="state-bbb",
                result={"user_email": "x@y.z", "refresh_token": "r"},
            )
            row = await repo.get_by_state(conn, "state-bbb")
            assert row["status"] == "authorized"
            assert row["result"]["user_email"] == "x@y.z"
        finally:
            await tr.rollback()


async def test_mark_failed(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await repo.insert(
                conn,
                state="state-ccc",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            await repo.mark_failed(conn, state="state-ccc", error="access_denied")
            row = await repo.get_by_state(conn, "state-ccc")
            assert row["status"] == "failed"
            assert row["result"]["error"] == "access_denied"
        finally:
            await tr.rollback()


async def test_delete_by_state(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await repo.insert(
                conn,
                state="state-ddd",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            deleted = await repo.delete_by_state(conn, "state-ddd")
            assert deleted == 1
            assert await repo.get_by_state(conn, "state-ddd") is None
        finally:
            await tr.rollback()


async def test_purge_expired(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await repo.insert(
                conn,
                state="alive",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            await repo.insert(
                conn,
                state="dead",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=-60,
            )
            n = await repo.purge_expired(conn)
            assert n >= 1
            assert await repo.get_by_state(conn, "dead") is None
            assert await repo.get_by_state(conn, "alive") is not None
        finally:
            await tr.rollback()
