"""Tests endpoint /v1/health (LOT_21A — version étendue)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _client_with_pool(pool_mock: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool_mock
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _pool_returning_epoch(epoch: int) -> MagicMock:
    fake_conn = AsyncMock()
    fake_conn.fetchval = AsyncMock(return_value=epoch)

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return fake_conn

        async def __aexit__(self, *_a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


@pytest.mark.asyncio
async def test_health_ok_when_db_responds_and_epoch_coherent() -> None:
    """Statut ok : DB UP + epoch cohérent + JWKS chargé."""
    from app.core import jwks_cache
    from app.core.cluster_state import cluster_state

    cluster_state.session_epoch = 5
    import datetime
    cluster_state.last_synced_at = datetime.datetime.now(datetime.UTC)
    jwks_cache._keys["test"] = {"kty": "RSA"}

    pool = _pool_returning_epoch(5)
    async with _client_with_pool(pool) as client:
        r = await client.get("/v1/health")

    jwks_cache._keys.pop("test", None)
    cluster_state.session_epoch = 0
    cluster_state.last_synced_at = None

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["epoch_coherent"] is True
    assert body["checks"]["jwks_loaded"] is True
    assert body["session_epoch"] == 5


@pytest.mark.asyncio
async def test_health_down_when_db_unreachable() -> None:
    """Statut down (503) si la DB ne répond pas."""
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=OSError("connection refused"))
    async with _client_with_pool(pool) as client:
        r = await client.get("/v1/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "down"
    assert "error" in body["checks"]["db"]


@pytest.mark.asyncio
async def test_health_degraded_when_jwks_empty() -> None:
    """Statut degraded (200) si DB OK mais aucun JWKS chargé."""
    from app.core import jwks_cache
    from app.core.cluster_state import cluster_state

    saved = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    cluster_state.session_epoch = 1
    import datetime
    cluster_state.last_synced_at = datetime.datetime.now(datetime.UTC)

    pool = _pool_returning_epoch(1)
    async with _client_with_pool(pool) as client:
        r = await client.get("/v1/health")

    jwks_cache._keys.update(saved)
    cluster_state.session_epoch = 0
    cluster_state.last_synced_at = None

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["jwks_loaded"] is False


@pytest.mark.asyncio
async def test_health_degraded_when_epoch_incoherent() -> None:
    """Statut degraded si epoch RAM < epoch DB (nœud en retard)."""
    from app.core import jwks_cache
    from app.core.cluster_state import cluster_state

    cluster_state.session_epoch = 3
    import datetime
    cluster_state.last_synced_at = datetime.datetime.now(datetime.UTC)
    jwks_cache._keys["test"] = {"kty": "RSA"}

    pool = _pool_returning_epoch(7)  # DB plus avancée
    async with _client_with_pool(pool) as client:
        r = await client.get("/v1/health")

    jwks_cache._keys.pop("test", None)
    cluster_state.session_epoch = 0
    cluster_state.last_synced_at = None

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["epoch_coherent"] is False
    assert body["checks"]["db_epoch"] == 7
