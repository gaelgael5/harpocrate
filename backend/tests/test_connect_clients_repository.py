"""Repository connect_clients — sur une vraie base (``HARPOCRATE_DB_DSN_TEST``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest

from app.db.repositories import connect_clients as repo


@pytest.fixture()
async def tx_conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            yield conn
        finally:
            await tr.rollback()


async def _insert(conn: asyncpg.Connection[asyncpg.Record], client_id: str = "ragflow") -> object:
    return await repo.db_insert(
        conn,
        client_id=client_id,
        name="Ragflow",
        description=None,
        redirect_uris=["https://rag.example/cb"],
        created_by_user_id=None,
    )


async def test_db_insert_then_get_by_id_returns_the_row(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    row = await _insert(tx_conn)
    fetched = await repo.db_get_by_id(tx_conn, row.id)  # type: ignore[attr-defined]
    assert fetched is not None
    assert fetched.client_id == "ragflow"
    assert fetched.redirect_uris == ["https://rag.example/cb"]
    assert fetched.active is True


async def test_db_get_by_id_returns_none_when_absent(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_get_by_id(tx_conn, uuid4()) is None


async def test_db_get_active_by_client_id_ignores_inactive(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    row = await _insert(tx_conn, "docflow")
    assert await repo.db_get_active_by_client_id(tx_conn, "docflow") is not None
    await repo.db_update(
        tx_conn,
        row.id,  # type: ignore[attr-defined]
        name="Ragflow",
        description=None,
        redirect_uris=["https://rag.example/cb"],
        active=False,
    )
    assert await repo.db_get_active_by_client_id(tx_conn, "docflow") is None


async def test_db_get_active_by_client_id_returns_none_when_unknown(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_get_active_by_client_id(tx_conn, "inconnu") is None


async def test_db_insert_duplicate_client_id_raises_unique_violation(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await _insert(tx_conn, "portal")
    with pytest.raises(asyncpg.UniqueViolationError):
        await _insert(tx_conn, "portal")


async def test_db_update_replaces_all_editable_fields(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    row = await _insert(tx_conn, "planner")
    updated = await repo.db_update(
        tx_conn,
        row.id,  # type: ignore[attr-defined]
        name="Planner v2",
        description="Planification",
        redirect_uris=["https://planner.example/cb", "https://planner.example/cb2"],
        active=True,
    )
    assert updated is not None
    assert updated.name == "Planner v2"
    assert updated.description == "Planification"
    assert updated.redirect_uris == ["https://planner.example/cb", "https://planner.example/cb2"]
    assert updated.updated_at >= updated.created_at


async def test_db_update_returns_none_when_absent(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    result = await repo.db_update(
        tx_conn,
        uuid4(),
        name="x",
        description=None,
        redirect_uris=["https://x.example/cb"],
        active=True,
    )
    assert result is None


async def test_db_list_returns_rows_ordered_by_name(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await repo.db_insert(
        tx_conn,
        client_id="zeta",
        name="Zeta",
        description=None,
        redirect_uris=["https://z.example/cb"],
        created_by_user_id=None,
    )
    await repo.db_insert(
        tx_conn,
        client_id="alpha",
        name="Alpha",
        description=None,
        redirect_uris=["https://a.example/cb"],
        created_by_user_id=None,
    )
    names = [r.name for r in await repo.db_list(tx_conn)]
    assert names.index("Alpha") < names.index("Zeta")
