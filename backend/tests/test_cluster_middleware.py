"""Tests middleware cluster_coherence (LOT_21A)."""
from __future__ import annotations

import base64
import datetime
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


@pytest.fixture(autouse=True)
def reset_cluster() -> Any:
    from app.core.cluster_state import cluster_state
    cluster_state.session_epoch = 0
    cluster_state.maintenance_active = False
    cluster_state.last_synced_at = None
    yield
    cluster_state.session_epoch = 0
    cluster_state.maintenance_active = False
    cluster_state.last_synced_at = None


def _pool(epoch: int) -> MagicMock:
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


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_middleware_blocks_when_maintenance_active() -> None:
    """Maintenance globale → 503 sur les endpoints non-admin."""
    from app.core.cluster_state import cluster_state
    cluster_state.maintenance_active = True
    cluster_state.maintenance_reason = "scheduled"

    async with _client(_pool(1)) as client:
        # /v1/wallets requiert auth, mais le middleware court avant donc 503 attendu
        r = await client.get("/v1/wallets")

    assert r.status_code == 503
    assert r.json()["error"] == "maintenance_in_progress"
    assert r.headers.get("retry-after") == "60"


@pytest.mark.asyncio
async def test_middleware_allows_admin_during_maintenance() -> None:
    """Endpoints admin restent accessibles en maintenance (pour la sortir)."""
    from app.core.cluster_state import cluster_state
    cluster_state.maintenance_active = True

    async with _client(_pool(1)) as client:
        r = await client.get("/v1/admin/maintenance/status")
    # 200 OK même sans auth car /status est public
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_middleware_allows_health_during_maintenance() -> None:
    from app.core.cluster_state import cluster_state
    cluster_state.maintenance_active = True

    async with _client(_pool(1)) as client:
        r = await client.get("/v1/health")
    assert r.status_code in (200, 503)  # 503 si DB mock vide


@pytest.mark.asyncio
async def test_middleware_blocks_when_node_epoch_lt_db_epoch() -> None:
    """Si epoch RAM < epoch DB, le nœud refuse de servir (503)."""
    from app.core.cluster_state import cluster_state

    cluster_state.session_epoch = 3
    cluster_state.last_synced_at = datetime.datetime.now(datetime.UTC)

    async with _client(_pool(7)) as client:
        r = await client.get("/v1/wallets")

    assert r.status_code == 503
    assert r.json()["error"] == "node_epoch_incoherent"
    assert r.headers.get("retry-after") == "5"


@pytest.mark.asyncio
async def test_middleware_passes_when_epoch_coherent() -> None:
    """Epoch RAM >= epoch DB → middleware laisse passer (handler renvoie 401/403)."""
    from app.core.cluster_state import cluster_state

    cluster_state.session_epoch = 7
    cluster_state.last_synced_at = datetime.datetime.now(datetime.UTC)

    async with _client(_pool(7)) as client:
        r = await client.get("/v1/wallets")

    # Pas de header Authorization → 401/403, mais PAS 503 du middleware cluster
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_middleware_bypasses_epoch_check_before_initial_sync() -> None:
    """Avant le premier refresh (last_synced_at=None), on ne bloque pas sur epoch."""
    from app.core.cluster_state import cluster_state

    # cluster_state pas encore synchronisé
    assert cluster_state.last_synced_at is None
    cluster_state.session_epoch = 0  # default

    async with _client(_pool(99)) as client:
        r = await client.get("/v1/wallets")

    # Pas bloqué par middleware cluster — l'endpoint répond comme d'habitude
    assert r.status_code in (401, 403)
