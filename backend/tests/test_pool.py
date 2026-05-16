"""Tests pool asyncpg — initialisation, fermeture, double-init idempotent."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


async def test_init_pool_creates_pool() -> None:
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=fake_pool) as create:
        from app.db import pool as pool_mod

        pool_mod._pool = None
        result = await pool_mod.init_pool()
        assert result is fake_pool
        create.assert_called_once()


async def test_init_pool_is_idempotent() -> None:
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=fake_pool) as create:
        from app.db import pool as pool_mod

        pool_mod._pool = None
        await pool_mod.init_pool()
        await pool_mod.init_pool()
        create.assert_called_once()


async def test_close_pool_clears_state() -> None:
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=fake_pool):
        from app.db import pool as pool_mod

        pool_mod._pool = None
        await pool_mod.init_pool()
        await pool_mod.close_pool()
        assert pool_mod._pool is None


async def test_get_pool_raises_if_not_initialized() -> None:
    from app.db import pool as pool_mod

    pool_mod._pool = None
    with pytest.raises(RuntimeError, match="not initialized"):
        await pool_mod.get_pool()


async def test_refresh_pool_closes_old_and_recreates() -> None:
    """refresh_pool : ferme l'ancien pool et en recrée un nouveau via init_pool.

    Utilisé après pairing standby : le step 6 vient d'écrire le password
    override file, le DSN effectif a changé, le pool doit prendre en compte
    le nouveau password sinon le backend reste en 503 jusqu'à un restart.
    """
    pool_a = AsyncMock()
    pool_a.close = AsyncMock()
    pool_b = AsyncMock()
    pool_b.close = AsyncMock()
    pools_iter = iter([pool_a, pool_b])

    async def fake_create(**kwargs: object) -> object:
        return next(pools_iter)

    with patch("asyncpg.create_pool", side_effect=fake_create):
        from app.db import pool as pool_mod

        pool_mod._pool = None
        first = await pool_mod.init_pool()
        assert first is pool_a

        refreshed = await pool_mod.refresh_pool()
        pool_a.close.assert_awaited_once()
        assert refreshed is pool_b
        assert pool_mod._pool is pool_b


async def test_refresh_pool_handles_uninitialized() -> None:
    """refresh_pool quand jamais init : se contente d'init, pas de close."""
    new_pool = AsyncMock()
    new_pool.close = AsyncMock()
    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=new_pool):
        from app.db import pool as pool_mod

        pool_mod._pool = None
        refreshed = await pool_mod.refresh_pool()
        assert refreshed is new_pool
        new_pool.close.assert_not_awaited()
