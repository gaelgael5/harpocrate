"""Tests endpoint webhook /v1/webhooks/notify (LOT_57 — standby)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock

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


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_standby_accepts_any_body_and_returns_200() -> None:
    """En attendant le branchement, l'endpoint accepte tout et répond 200."""
    pool = _make_pool(MagicMock())
    async with _client(pool) as cli:
        r = await cli.post(
            "/v1/webhooks/notify",
            json={"event": "message.sent", "transactionId": "tx-1"},
        )
    assert r.status_code == 200
    assert r.json() == {"received": True}


@pytest.mark.asyncio
async def test_standby_accepts_unknown_format() -> None:
    """Pas de validation tant qu'on ne connaît pas le provider final."""
    pool = _make_pool(MagicMock())
    async with _client(pool) as cli:
        r = await cli.post(
            "/v1/webhooks/notify",
            json={"random": "garbage"},
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_standby_accepts_empty_body() -> None:
    pool = _make_pool(MagicMock())
    async with _client(pool) as cli:
        r = await cli.post("/v1/webhooks/notify", content=b"")
    assert r.status_code == 200
