"""Migration 035 et repository listmonk_templates sur une vraie base
(``HARPOCRATE_DB_DSN_TEST``) : résolution par culture avec repli, import legacy
idempotent, contraintes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.db.repositories import cultures as cultures_repo
from app.db.repositories import listmonk_templates as repo


@pytest.fixture()
async def tx_conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    """Connexion dans une transaction annulée en fin de test : rien ne persiste.
    La table est vidée dans la transaction pour ne pas dépendre de l'import legacy."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("DELETE FROM listmonk_templates")
            yield conn
        finally:
            await tr.rollback()


async def _set(conn: asyncpg.Connection[asyncpg.Record], code: str, template_id: int) -> None:
    await repo.db_upsert(
        conn,
        purpose="recovery",
        culture_code=code,
        template_id=template_id,
        updated_by_user_id=None,
    )


async def test_resolve_returns_user_culture_template(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await _set(tx_conn, "en", 6)
    await _set(tx_conn, "fr", 5)
    resolved = await repo.db_resolve(tx_conn, "recovery", "fr")
    assert resolved is not None
    assert (resolved.template_id, resolved.culture_code) == (5, "fr")


async def test_resolve_falls_back_to_default_when_culture_has_no_template(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await _set(tx_conn, "en", 6)
    resolved = await repo.db_resolve(tx_conn, "recovery", "fr")
    assert resolved is not None
    assert (resolved.template_id, resolved.culture_code) == (6, "en")


async def test_resolve_ignores_template_of_disabled_culture(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await _set(tx_conn, "en", 6)
    await _set(tx_conn, "fr", 5)
    await cultures_repo.db_set_enabled(tx_conn, "fr", False)
    resolved = await repo.db_resolve(tx_conn, "recovery", "fr")
    assert resolved is not None
    assert resolved.culture_code == "en"


async def test_resolve_null_locale_uses_default(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await _set(tx_conn, "en", 6)
    resolved = await repo.db_resolve(tx_conn, "recovery", None)
    assert resolved is not None
    assert resolved.template_id == 6


async def test_resolve_without_any_template_returns_none(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_resolve(tx_conn, "recovery", "fr") is None


async def test_upsert_replaces_template_id(tx_conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await _set(tx_conn, "fr", 5)
    await _set(tx_conn, "fr", 8)
    row = await repo.db_get_for_update(tx_conn, "recovery", "fr")
    assert row is not None and row.template_id == 8


async def test_delete_missing_template_returns_false(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await repo.db_delete(tx_conn, "recovery", "fr") is False
    assert await repo.db_get_for_update(tx_conn, "recovery", "fr") is None


async def test_import_legacy_inserts_when_table_empty(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    inserted = await repo.db_import_legacy(tx_conn, "recovery", {"fr": 5, "en": 6})
    assert inserted == 2
    rows = await repo.db_list(tx_conn)
    assert {(r.culture_code, r.template_id) for r in rows} == {("fr", 5), ("en", 6)}


async def test_import_legacy_never_overwrites_existing_templates(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await _set(tx_conn, "en", 9)
    inserted = await repo.db_import_legacy(tx_conn, "recovery", {"fr": 5, "en": 6})
    assert inserted == 0
    rows = await repo.db_list(tx_conn)
    assert [(r.culture_code, r.template_id) for r in rows] == [("en", 9)]


@pytest.mark.parametrize(
    ("purpose", "template_id", "error"),
    [
        ("welcome", 5, asyncpg.CheckViolationError),
        ("recovery", 0, asyncpg.CheckViolationError),
    ],
)
async def test_listmonk_templates_constraints(
    tx_conn: asyncpg.Connection[asyncpg.Record],
    purpose: str,
    template_id: int,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await tx_conn.execute(
            "INSERT INTO listmonk_templates (purpose, culture_code, template_id) "
            "VALUES ($1, 'fr', $2)",
            purpose,
            template_id,
        )


async def test_listmonk_templates_unknown_culture_rejected(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await _set(tx_conn, "xx", 5)
