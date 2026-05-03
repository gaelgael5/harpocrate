"""Tests des endpoints /v1/admin/system/* et /v1/admin/users — LOT_12C."""
from __future__ import annotations

import base64
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


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


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}})
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])
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


@pytest.mark.asyncio
async def test_system_info_requires_admin() -> None:
    """GET /v1/admin/system/info → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/system/info", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_system_info_returns_counts() -> None:
    """GET /v1/admin/system/info → 200 avec les compteurs."""
    conn = _make_conn()
    conn.fetchval = AsyncMock(side_effect=[5, 4, 10, 20, 3, 2, 100])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/system/info", headers=_admin_header())
    assert r.status_code == 200
    body = r.json()
    assert body["users_count"] == 5
    assert body["wallets_count"] == 10


@pytest.mark.asyncio
async def test_list_users_requires_admin() -> None:
    """GET /v1/admin/users → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/users", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_users_empty() -> None:
    """GET /v1/admin/users → 200 liste vide."""
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=0)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/users", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["users"] == []
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_admin_audit_log_requires_admin() -> None:
    """GET /v1/admin/audit-log → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/audit-log", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_audit_log_empty() -> None:
    """GET /v1/admin/audit-log → 200 liste vide."""
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/audit-log", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["events"] == []
    assert r.json()["next_cursor"] is None
