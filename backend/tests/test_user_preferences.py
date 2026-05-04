"""Tests endpoints préférences utilisateur — LOT_16."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_USER_UUID = uuid.uuid4()


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
    from app.services import snapshot_scheduler as sched_svc
    mock_scheduler = MagicMock()
    mock_scheduler.restart = AsyncMock()
    mock_scheduler.trigger = AsyncMock()
    monkeypatch.setattr(sched_svc, "_scheduler", mock_scheduler)


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


def _make_user_row() -> MagicMock:
    from app.models.db.user import UserRow
    u = MagicMock(spec=UserRow)
    u.id = _USER_UUID
    u.keycloak_sub = "test-sub-123"
    u.email = "test@example.com"
    u.display_name = "Test User"
    u.kdf_memory_kb = 65536
    u.kdf_iterations = 3
    u.kdf_parallelism = 1
    u.rsa_key_size = 4096
    u.created_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    u.last_unlock_at = None
    u.preferred_locale = "en"
    u.quarantine_until = None
    u.force_reverify_next_login = False
    u.disabled_at = None
    return u


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="UPDATE 1")
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
async def test_patch_preferences_locale_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _make_conn()
    user = _make_user_row()
    conn.fetchrow = AsyncMock(return_value=user)

    import app.db.repositories.users as users_repo
    monkeypatch.setattr(users_repo, "get_by_keycloak_sub", AsyncMock(return_value=user))

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            "/v1/me/preferences",
            headers=_user_header(),
            json={"preferred_locale": "fr"},
        )
    assert r.status_code == 200
    assert r.json()["preferred_locale"] == "fr"


@pytest.mark.asyncio
async def test_patch_preferences_locale_invalid_400(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _make_conn()
    user = _make_user_row()
    conn.fetchrow = AsyncMock(return_value=user)

    import app.db.repositories.users as users_repo
    monkeypatch.setattr(users_repo, "get_by_keycloak_sub", AsyncMock(return_value=user))

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            "/v1/me/preferences",
            headers=_user_header(),
            json={"preferred_locale": "de"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_me_returns_preferred_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _make_conn()
    user = _make_user_row()
    user.preferred_locale = "fr"

    import app.db.repositories.users as users_repo
    monkeypatch.setattr(users_repo, "get_by_keycloak_sub", AsyncMock(return_value=user))

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/me", headers=_user_header())
    assert r.status_code == 200
    assert r.json()["preferred_locale"] == "fr"
