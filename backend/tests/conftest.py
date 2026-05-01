"""Shared pytest fixtures."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def patch_asyncpg_create_pool() -> Iterator[None]:
    """Stub asyncpg.create_pool pour les tests unitaires.

    Les tests d'intégration qui ont besoin d'une vraie DB demandent le fixture
    ``real_db_pool`` ; le stub n'interfère pas car asyncpg.create_pool est
    seulement utilisé par le lifespan FastAPI.
    """
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", return_value=fake_pool):
        yield


_REAL_DB_DSN_ENV = "HARPOCRATE_DB_DSN_TEST"


@pytest_asyncio.fixture(scope="session")
async def real_db_pool() -> AsyncIterator[asyncpg.Pool]:
    """Pool asyncpg connecté à une vraie DB de test.

    Activé seulement si ``HARPOCRATE_DB_DSN_TEST`` est défini dans l'env.
    Sinon, les tests qui dépendent de ce fixture sont skipés.
    Les tables sont supposées déjà migrées (la migration 001 doit avoir tourné).
    Chaque test doit nettoyer ses données.
    """
    dsn = os.environ.get(_REAL_DB_DSN_ENV)
    if not dsn:
        pytest.skip(
            f"{_REAL_DB_DSN_ENV} non défini — tests d'intégration DB skippés"
        )
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()
