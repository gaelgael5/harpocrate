"""Tests endpoints /v1/admin/replication/* (LOT_20)."""
from __future__ import annotations

import base64
import datetime
import uuid
from typing import Any
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

_NOW = datetime.datetime(2026, 5, 5, tzinfo=datetime.UTC)
_STRAT_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")


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
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_PASSWORD", "test-password")
    import app.core.config
    app.core.config.settings = app.core.config.Settings()


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


def _strategy_row() -> dict[str, Any]:
    return {
        "id": _STRAT_ID,
        "type": "none",
        "label": "Standalone",
        "description": "Postgres standalone",
        "config": {},
        "enabled": True,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by_user_id": None,
    }


@pytest.mark.asyncio
async def test_list_strategies_requires_admin() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/replication/strategies")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_strategies_returns_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.repositories import replication_strategies as repo

    async def fake_list(_conn: Any) -> list[Any]:
        return [_strategy_row()]

    monkeypatch.setattr(repo, "list_strategies", fake_list)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/replication/strategies", headers=_admin_header())

    assert r.status_code == 200, r.text
    body = r.json()
    assert "strategies" in body
    assert body["strategies"][0]["type"] == "none"
    assert body["strategies"][0]["is_active"] is True


@pytest.mark.asyncio
async def test_activate_strategy_returns_404_when_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import replication as svc

    async def fake_activate(_conn: Any, _id: uuid.UUID) -> bool:
        return False

    monkeypatch.setattr(svc, "activate", fake_activate)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            f"/v1/admin/replication/strategies/{_STRAT_ID}/activate",
            headers=_admin_header(),
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_activate_strategy_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import replication as svc

    async def fake_activate(_conn: Any, _id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(svc, "activate", fake_activate)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            f"/v1/admin/replication/strategies/{_STRAT_ID}/activate",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["activated"] is True


@pytest.mark.asyncio
async def test_status_when_no_active_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import replication as svc

    async def fake_active(_conn: Any) -> Any:
        return None

    monkeypatch.setattr(svc, "get_active", fake_active)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/replication/status", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["status"] == "no_active_strategy"


@pytest.mark.asyncio
async def test_status_returns_live_state_for_active_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.replication import NoneStrategy
    from app.services import replication as svc

    fake_row = _strategy_row()
    fake_strategy = NoneStrategy()

    async def fake_active(_conn: Any) -> Any:
        return fake_row, fake_strategy

    monkeypatch.setattr(svc, "get_active", fake_active)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/replication/status", headers=_admin_header())
    assert r.status_code == 200
    body = r.json()
    assert body["strategy"]["type"] == "none"
    assert body["live"]["status"] == "ok"
