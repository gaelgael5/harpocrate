"""Migration 036 et repository listmonk_connection sur une vraie base
(``HARPOCRATE_DB_DSN_TEST``) : ligne unique, upsert, insertion sans écrasement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.db.repositories import listmonk_connection as repo


@pytest.fixture()
async def tx_conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    """Transaction annulée en fin de test ; la table est vidée pour ne pas dépendre de
    la reprise du .env au boot."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("DELETE FROM listmonk_connection")
            yield conn
        finally:
            await tr.rollback()


async def test_get_without_connection_returns_none(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_get(tx_conn) is None


async def test_upsert_creates_then_replaces_single_row(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await repo.db_upsert(
        tx_conn, url="http://a.lan", api_user="u1", token_encrypted=b"t1", updated_by_user_id=None
    )
    await repo.db_upsert(
        tx_conn, url="http://b.lan", api_user="u2", token_encrypted=b"t2", updated_by_user_id=None
    )
    row = await repo.db_get(tx_conn)
    assert row is not None
    assert (row.url, row.api_user, row.token_encrypted) == ("http://b.lan", "u2", b"t2")
    assert await tx_conn.fetchval("SELECT count(*) FROM listmonk_connection") == 1


async def test_insert_if_absent_never_overwrites(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_insert_if_absent(
        tx_conn, url="http://a.lan", api_user="u1", token_encrypted=b"t1"
    )
    assert not await repo.db_insert_if_absent(
        tx_conn, url="http://b.lan", api_user="u2", token_encrypted=b"t2"
    )
    row = await repo.db_get(tx_conn)
    assert row is not None and row.url == "http://a.lan"


async def test_second_row_is_rejected(tx_conn: asyncpg.Connection[asyncpg.Record]) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await tx_conn.execute(
            "INSERT INTO listmonk_connection (id, url, api_user, token_encrypted) "
            "VALUES (FALSE, 'http://a.lan', 'u', '\\x00')"
        )
