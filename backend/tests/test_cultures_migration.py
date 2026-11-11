"""Migration 034 — table cultures (langues ISO 639-1 activables).

Vérifie sur une vraie base (``HARPOCRATE_DB_DSN_TEST``) l'amorçage et les invariants que
la base porte seule : une seule culture par défaut, forcément activée, code ISO 639-1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.db.repositories import cultures as repo

# Nombre de codes ISO 639-1 en vigueur (le code retiré « sh » n'est pas repris).
_ISO_639_1_COUNT = 183


@pytest.fixture()
async def tx_conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    """Connexion dans une transaction annulée en fin de test : rien ne persiste."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            yield conn
        finally:
            await tr.rollback()


async def test_cultures_seed_contains_all_iso_639_1_codes(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    rows = await repo.db_list(tx_conn)
    assert len(rows) == _ISO_639_1_COUNT
    assert all(len(r.code) == 2 and r.code.islower() for r in rows)


async def test_cultures_seed_enables_en_fr_with_en_default(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    rows = await repo.db_list(tx_conn)
    assert sorted(r.code for r in rows if r.enabled) == ["en", "fr"]
    assert [r.code for r in rows if r.is_default] == ["en"]


async def test_cultures_get_unknown_code_returns_none(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_get(tx_conn, "xx") is None


async def test_cultures_second_default_is_rejected_by_unique_index(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    with pytest.raises(asyncpg.UniqueViolationError):
        await repo.db_mark_default(tx_conn, "fr")


async def test_cultures_default_must_be_enabled(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await repo.db_clear_default(tx_conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await repo.db_mark_default(tx_conn, "de")


async def test_cultures_switch_default_in_one_transaction(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await repo.db_clear_default(tx_conn)
    row = await repo.db_mark_default(tx_conn, "fr")
    assert row is not None and row.is_default
    rows = await repo.db_list(tx_conn)
    assert [r.code for r in rows if r.is_default] == ["fr"]


async def test_cultures_set_enabled_unknown_code_returns_none(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_set_enabled(tx_conn, "xx", True) is None


@pytest.mark.parametrize("code", ["FR", "fra", "f1"])
async def test_cultures_code_format_is_enforced(
    tx_conn: asyncpg.Connection[asyncpg.Record], code: str
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await tx_conn.execute(
            "INSERT INTO cultures (code, english_name) VALUES ($1, 'Bogus')", code
        )


async def test_cultures_default_switch_lock_runs_in_transaction(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await repo.db_lock_default_switch(tx_conn)
    held = await tx_conn.fetchval(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
    )
    assert held == 1
