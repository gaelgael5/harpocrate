"""Shared pytest fixtures."""
from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio

# Clé HMAC stable pour tous les tests — doit correspondre à _HMAC_KEY_B64
# dans test_api_keys.py (b"k" * 32 en base64) afin d'éviter les pollutions
# inter-fichiers quand les fixtures function-scoped changent les env vars.
_TEST_HMAC_KEY_B64 = base64.b64encode(b"k" * 32).decode()


@pytest.fixture(autouse=True, scope="session")
def _initialize_settings_singleton() -> None:
    """Crée le singleton settings avant le premier test avec des valeurs stables.

    Empêche la pollution de settings.hmac_key entre fichiers de test causée
    par l'ordre d'exécution des fixtures function-scoped.
    """
    os.environ.setdefault("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    os.environ.setdefault("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    os.environ.setdefault("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    os.environ.setdefault("HARPOCRATE_KEYCLOAK_CLIENT_ID", "harpocrate-vault")
    os.environ.setdefault("HARPOCRATE_HMAC_KEY", _TEST_HMAC_KEY_B64)
    os.environ.setdefault("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    from app.core.config import settings as _settings  # noqa: F401


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
async def real_db_pool() -> AsyncIterator[asyncpg.Pool[asyncpg.Record]]:
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
    pool: asyncpg.Pool[asyncpg.Record] = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=4
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture()
def mock_db_conn() -> MagicMock:
    """Connexion asyncpg mockée pour les tests unitaires de services/repositories."""
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)

    class FakeTxCtx:
        async def __aenter__(self) -> FakeTxCtx:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    conn.transaction = MagicMock(return_value=FakeTxCtx())
    return conn
