"""Tests P1.5 — Endpoints publics de secret-types accessibles via API key."""

from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_API_KEY_TOKEN = "hrpv_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890aBcDeFgHi"  # placeholder


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _make_client_with_mocked_pool() -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    pool_mod._pool = pool

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_list_types_with_api_key_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /v1/secret-types avec un Bearer hrpv_* doit retourner 200."""
    # Mock validate_api_key_token pour qu'il renvoie un caller valide sans toucher la BDD
    from app.core import api_key_auth as auth_mod

    class _FakeCaller:
        owner_user_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        wallet_id = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
        permissions = 63

    async def _fake_validate(token: str, *, pool: Any, required_permission: int = 0) -> Any:
        return _FakeCaller()

    monkeypatch.setattr(auth_mod, "validate_api_key_token", _fake_validate)

    async with _make_client_with_mocked_pool() as cli:
        r = await cli.get(
            "/v1/secret-types",
            headers={"Authorization": f"Bearer {_API_KEY_TOKEN}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "types" in body


@pytest.mark.asyncio
async def test_get_type_with_api_key_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /v1/secret-types/{uuid} avec hrpv_* doit retourner 200 (ou 404 si pas trouvé)."""
    from app.core import api_key_auth as auth_mod

    class _FakeCaller:
        owner_user_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        wallet_id = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
        permissions = 63

    async def _fake_validate(token: str, *, pool: Any, required_permission: int = 0) -> Any:
        return _FakeCaller()

    monkeypatch.setattr(auth_mod, "validate_api_key_token", _fake_validate)

    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")

    async with _make_client_with_mocked_pool() as cli:
        r = await cli.get(
            f"/v1/secret-types/{type_uuid}",
            headers={"Authorization": f"Bearer {_API_KEY_TOKEN}"},
        )

    # 404 acceptable (le mock renvoie None pour fetchrow) — ce ne doit PAS être 401/403
    assert r.status_code in (200, 404), r.text


@pytest.mark.asyncio
async def test_list_types_without_token_still_returns_401() -> None:
    """GET /v1/secret-types sans Authorization → 401."""
    async with _make_client_with_mocked_pool() as cli:
        r = await cli.get("/v1/secret-types")
    assert r.status_code == 401
