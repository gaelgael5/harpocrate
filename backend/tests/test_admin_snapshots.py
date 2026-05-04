"""Tests des endpoints /v1/admin/snapshots/* — LOT_14."""
from __future__ import annotations

import base64
import datetime
import json
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")
    monkeypatch.setenv("HARPOCRATE_AGE_PUBLIC_KEY", "age1qyqszqgpqyqszqgpqyqszqgpqyqszqgpq")

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
def patch_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub le scheduler pour tous les tests (pas de vraie tâche asyncio)."""
    from app.services import snapshot_scheduler as sched_svc
    mock_scheduler = MagicMock()
    mock_scheduler.restart = AsyncMock()
    mock_scheduler.trigger = AsyncMock()
    monkeypatch.setattr(sched_svc, "_scheduler", mock_scheduler)


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(
        extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}, "email": "admin@test.com"}
    )
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
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


_DEFAULT_POLICY = {
    "interval_minutes": 0,
    "retention": {"hourly": 24, "daily": 7, "weekly": 4, "monthly": 12, "yearly": 5},
    "push_remote_after_snapshot": False,
    "remote_destinations_to_push": [],
    "skip_if_no_change": True,
}


# ─── GET /policy ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_policy_requires_admin() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/snapshots/policy", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_policy_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import snapshot_scheduler as sched_svc

    async def _get_policy(conn: Any) -> Any:
        from app.services.gfs_rotation import GFSPolicy
        return GFSPolicy()

    monkeypatch.setattr(sched_svc, "get_policy", _get_policy)

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/snapshots/policy", headers=_admin_header())
    assert r.status_code == 200
    data = r.json()
    assert data["interval_minutes"] == 0
    assert data["retention"]["hourly"] == 24


# ─── PUT /policy ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_policy_requires_admin() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.put("/v1/admin/snapshots/policy", json=_DEFAULT_POLICY, headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_policy_invalid_interval() -> None:
    conn = _make_conn()
    body = {**_DEFAULT_POLICY, "interval_minutes": 2}
    async with _make_client(_make_pool(conn)) as client:
        r = await client.put("/v1/admin/snapshots/policy", json=body, headers=_admin_header())
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_interval"


@pytest.mark.asyncio
async def test_update_policy_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import snapshot_scheduler as sched_svc

    calls: list[Any] = []

    async def _set_policy(conn: Any, policy: Any) -> None:
        calls.append(policy)

    monkeypatch.setattr(sched_svc, "set_policy", _set_policy)

    conn = _make_conn()
    body = {**_DEFAULT_POLICY, "interval_minutes": 60}
    async with _make_client(_make_pool(conn)) as client:
        r = await client.put("/v1/admin/snapshots/policy", json=body, headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["interval_minutes"] == 60
    assert len(calls) == 1


# ─── POST /trigger ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_requires_admin() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post("/v1/admin/snapshots/trigger", json={}, headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_trigger_skipped_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import snapshot_scheduler as sched_svc

    mock_scheduler = MagicMock()
    mock_scheduler.trigger = AsyncMock(side_effect=sched_svc._NoChangeError())
    mock_scheduler.restart = AsyncMock()
    monkeypatch.setattr(sched_svc, "_scheduler", mock_scheduler)

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post("/v1/admin/snapshots/trigger", json={}, headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["skipped"] is True


@pytest.mark.asyncio
async def test_trigger_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import snapshot_scheduler as sched_svc
    from app.db.repositories.backups import BackupRecord

    fake_backup = BackupRecord(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000001"),
        filename="harpocrate-snapshot-2026-01-01-12-00-00.tar.age",
        size_bytes=12345,
        checksum_sha256="abc",
        age_recipient="age1...",
        manifest={},
        description="Auto snapshot",
        created_at=_NOW,
        created_by_user_id=None,
        imported=False,
        tier="hourly",
    )

    mock_scheduler = MagicMock()
    mock_scheduler.trigger = AsyncMock(return_value=fake_backup)
    mock_scheduler.restart = AsyncMock()
    monkeypatch.setattr(sched_svc, "_scheduler", mock_scheduler)

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/snapshots/trigger",
            json={"force": True, "description": "test"},
            headers=_admin_header(),
        )
    assert r.status_code == 202
    assert r.json()["skipped"] is False
    assert r.json()["snapshot"]["tier"] == "hourly"


# ─── GET /history ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_requires_admin() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/snapshots/history", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_history_invalid_tier() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/snapshots/history?tier=invalid", headers=_admin_header())
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_tier"


@pytest.mark.asyncio
async def test_history_empty() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/snapshots/history", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["snapshots"] == []
