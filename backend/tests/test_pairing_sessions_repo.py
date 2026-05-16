"""Tests CRUD du repository pairing_sessions (LOT 1)."""

from __future__ import annotations

import asyncpg

from app.db.repositories import pairing_sessions as repo


async def test_create_and_fetch(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    async with real_db_pool.acquire() as conn:
        sid = await repo.create(
            conn,
            role="master",
            code="1234",
            partner_url="https://b.example/",
            ttl_seconds=600,
            actor_user_id=None,
        )
        row = await repo.get(conn, sid)
        await conn.execute("DELETE FROM pairing_session WHERE id = $1", sid)
    assert row is not None
    assert row["role"] == "master"
    assert row["code"] == "1234"
    assert row["status"] == "pending"
    assert row["current_step_idx"] == 0


async def test_get_active_by_code(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    async with real_db_pool.acquire() as conn:
        sid = await repo.create(
            conn,
            role="master",
            code="9876",
            partner_url=None,
            ttl_seconds=600,
            actor_user_id=None,
        )
        found = await repo.get_active_by_code(conn, "9876")
        await conn.execute("DELETE FROM pairing_session WHERE id = $1", sid)
    assert found is not None and found["id"] == sid


async def test_increment_attempts(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    async with real_db_pool.acquire() as conn:
        sid = await repo.create(
            conn,
            role="master",
            code="5555",
            partner_url=None,
            ttl_seconds=600,
            actor_user_id=None,
        )
        n = await repo.increment_attempts(conn, sid)
        await conn.execute("DELETE FROM pairing_session WHERE id = $1", sid)
    assert n == 1


async def test_set_status_payload_step(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    async with real_db_pool.acquire() as conn:
        sid = await repo.create(
            conn,
            role="standby",
            code="0001",
            partner_url="https://a.example/",
            ttl_seconds=600,
            actor_user_id=None,
        )
        await repo.set_status(conn, sid, "wizard")
        await repo.set_payload(conn, sid, {"replication_user": "rep_x"})
        await repo.set_step_idx(conn, sid, 3)
        row = await repo.get(conn, sid)
        await conn.execute("DELETE FROM pairing_session WHERE id = $1", sid)
    assert row is not None
    assert row["status"] == "wizard"
    assert row["payload"]["replication_user"] == "rep_x"
    assert row["current_step_idx"] == 3


async def test_expire_old(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    """Une session avec ttl_seconds=0 devient 'expired' au prochain expire_old."""
    async with real_db_pool.acquire() as conn:
        sid = await repo.create(
            conn,
            role="master",
            code="3333",
            partner_url=None,
            ttl_seconds=0,
            actor_user_id=None,
        )
        count = await repo.expire_old(conn)
        row = await repo.get(conn, sid)
        await conn.execute("DELETE FROM pairing_session WHERE id = $1", sid)
    assert count >= 1  # peut être >1 si d'autres sessions expirent en même temps
    assert row is not None
    assert row["status"] == "expired"
