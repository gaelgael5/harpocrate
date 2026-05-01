"""Tests endpoint /v1/health."""
from __future__ import annotations

import base64
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


def _client_with_pool(pool_mock: AsyncMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool_mock
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_health_ok_when_db_responds() -> None:
    fake_conn = AsyncMock()
    fake_conn.fetchval = AsyncMock(return_value=1)

    # Create a context manager that returns the connection
    class FakeAcquireCtx:
        async def __aenter__(self) -> AsyncMock:
            return fake_conn

        async def __aexit__(self, *args: object) -> None:
            pass

    fake_pool = MagicMock()
    fake_pool.acquire.return_value = FakeAcquireCtx()

    client = _client_with_pool(fake_pool)
    r = await client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0", "db": "ok"}


@pytest.mark.asyncio
async def test_health_degraded_when_db_unreachable() -> None:
    fake_pool = MagicMock()
    fake_pool.acquire.side_effect = OSError("connection refused")

    client = _client_with_pool(fake_pool)
    r = await client.get("/v1/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"
