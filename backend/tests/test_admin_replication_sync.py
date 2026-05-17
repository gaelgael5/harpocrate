"""Tests endpoints /v1/admin/replication/sync/* (LOT_21B)."""
from __future__ import annotations

import base64
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "test-client")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_ENABLED", "true")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_USERNAME", "admin")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_PASSWORD", "x")
    monkeypatch.setenv("HARPOCRATE_INSTANCE_ID", "test-node")
    # Pas de réassignation de settings (cf. test_admin_remote_backups.py:env).
    import app.core.config

    _new_s = app.core.config.Settings()
    for _a, _v in _new_s.model_dump().items():
        monkeypatch.setattr(app.core.config.settings, _a, _v)


def _admin_token() -> str:
    from app.core.config import settings
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    payload = {
        "sub": "admin",
        "email": "admin@test",
        "iat": now,
        "exp": now + 3600,
        "iss": "harpocrate-local",
        "aud": settings.keycloak_client_id,
        "realm_access": {"roles": [settings.admin_role_name]},
    }
    secret = base64.b64decode(settings.hmac_key)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_token()}"}


def _make_pool(conn: MagicMock) -> MagicMock:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn

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
async def test_sync_status_requires_admin() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/replication/sync/status")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_sync_status_returns_disabled_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans config sync, status renvoie enabled=false + listes vides."""
    from app.db.repositories import sync_replication as repo

    async def fake_get_cursor(_conn: Any) -> int:
        return 0

    async def fake_list_states(_conn: Any) -> list[Any]:
        return []

    monkeypatch.setattr(repo, "get_push_cursor", fake_get_cursor)
    monkeypatch.setattr(repo, "list_states", fake_list_states)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get(
            "/v1/admin/replication/sync/status", headers=_admin_header()
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["publisher_running"] is False
    assert body["consumer_running"] is False
    assert body["push_cursor"] == 0
    assert body["peers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_peers_with_lag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.repositories import sync_replication as repo

    async def fake_get_cursor(_conn: Any) -> int:
        return 100

    async def fake_list_states(_conn: Any) -> list[Any]:
        return [{
            "peer_emitter": "node-other",
            "last_applied_seq": 50,
            "last_acked_seq": 49,
            "last_received_seq": 60,
            "last_seen_at": datetime.datetime(2026, 5, 5, tzinfo=datetime.UTC),
            "status": "synced",
        }]

    monkeypatch.setattr(repo, "get_push_cursor", fake_get_cursor)
    monkeypatch.setattr(repo, "list_states", fake_list_states)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get(
            "/v1/admin/replication/sync/status", headers=_admin_header()
        )
    body = r.json()
    assert body["push_cursor"] == 100
    assert len(body["peers"]) == 1
    peer = body["peers"][0]
    assert peer["emitter"] == "node-other"
    assert peer["lag"] == 10  # received(60) - applied(50)


@pytest.mark.asyncio
async def test_reset_cursor_503_when_publisher_not_running() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/replication/sync/cursor/reset",
            headers=_admin_header(),
            json={"new_cursor": 0},
        )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "sync_publisher_not_running"


@pytest.mark.asyncio
async def test_reset_cursor_calls_publisher_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import sync_replication_service as svc

    fake_publisher = MagicMock()
    fake_publisher.reset_cursor = AsyncMock(return_value=None)

    monkeypatch.setattr(svc, "get_publisher", lambda: fake_publisher)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/replication/sync/cursor/reset",
            headers=_admin_header(),
            json={"new_cursor": 42},
        )
    assert r.status_code == 200
    assert r.json()["reset_to"] == 42
    fake_publisher.reset_cursor.assert_awaited_once_with(42)
