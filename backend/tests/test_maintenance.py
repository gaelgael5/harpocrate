"""Tests du mode maintenance (middleware + endpoints) — LOT_12A."""
from __future__ import annotations

import base64
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security
    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache
    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


@pytest.fixture(autouse=True)
def reset_maintenance() -> Generator[None, None, None]:
    """Remet le mode maintenance à False entre chaque test (legacy + cluster_state)."""
    from app.core.cluster_state import cluster_state
    from app.core.maintenance import maintenance_state
    maintenance_state.active = False
    maintenance_state.reason = None
    maintenance_state.started_at = None
    maintenance_state.effective_at = None
    maintenance_state.estimated_end_at = None
    cluster_state.maintenance_active = False
    cluster_state.maintenance_reason = None
    cluster_state.maintenance_started_at = None
    cluster_state.maintenance_effective_at = None
    cluster_state.maintenance_estimated_end_at = None
    yield
    maintenance_state.active = False
    cluster_state.maintenance_active = False


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock(return_value=None)
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}})
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


@pytest.mark.asyncio
async def test_maintenance_status_public_initially_inactive() -> None:
    """GET /v1/admin/maintenance/status est public et retourne inactive par défaut."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/maintenance/status")
    assert r.status_code == 200
    assert r.json()["active"] is False


@pytest.mark.asyncio
async def test_maintenance_enable_requires_admin() -> None:
    """POST /v1/admin/maintenance/enable → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/maintenance/enable",
            json={"reason": "test"},
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_enable_sets_active() -> None:
    """POST /v1/admin/maintenance/enable active le mode maintenance."""
    conn = _make_conn()
    conn.execute = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/maintenance/enable",
            json={"reason": "DB maintenance", "delay_seconds": 0, "estimated_duration_minutes": 5},
            headers=_admin_header(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True

    from app.core.maintenance import maintenance_state
    assert maintenance_state.active is True


@pytest.mark.asyncio
async def test_maintenance_blocks_normal_requests() -> None:
    """En mode maintenance, les requêtes non-admin reçoivent 503."""
    from app.core.cluster_state import cluster_state
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True
    cluster_state.maintenance_active = True

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/wallets", headers=_user_header())
    assert r.status_code == 503
    assert r.json()["error"] == "maintenance_in_progress"


@pytest.mark.asyncio
async def test_maintenance_allows_health() -> None:
    """En mode maintenance, /v1/health passe toujours."""
    from app.core.cluster_state import cluster_state
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True
    cluster_state.maintenance_active = True

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_allows_admin_routes() -> None:
    """En mode maintenance, /v1/admin/* passe."""
    from app.core.cluster_state import cluster_state
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True
    cluster_state.maintenance_active = True

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/maintenance/status")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_disable() -> None:
    """POST /v1/admin/maintenance/disable désactive le mode."""
    from app.core.cluster_state import cluster_state
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True
    cluster_state.maintenance_active = True

    conn = _make_conn()
    conn.execute = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/maintenance/disable",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    assert maintenance_state.active is False
