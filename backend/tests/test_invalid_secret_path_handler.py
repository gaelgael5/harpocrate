"""Vérifie que les noms de secret invalides retournent 400 invalid_secret_path
(et non 422 ValidationError de Pydantic)."""

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
    make_jwt_token,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_FAKE_ENC_VALUE = base64.b64encode(b"fake_encrypted_secret_value").decode()

# Permissions : PERM_WRITE (bit 2 = 0x02) — suffisant pour POST /secrets
_PERM_WRITE = 0x02


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(key, default)


_USER_ROW = FakeRecord(
    {
        "id": _CALLER_ID,
        "keycloak_sub": "test-sub-001",
        "email": "alice@example.com",
        "display_name": "Alice",
        "rsa_public_key": b"x",
        "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16,
        "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x",
        "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536,
        "kdf_iterations": 3,
        "kdf_parallelism": 4,
        "rsa_key_size": 2048,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_unlock_at": None,
        "quarantine_until": None,
        "quarantine_reason": None,
        "force_reverify_next_login": False,
        "disabled_at": None,
        "disabled_reason": None,
    }
)

_WALLET_ROW = FakeRecord(
    {
        "id": _WALLET_ID,
        "name": "test-wallet",
        "description": None,
        "owner_user_id": _CALLER_ID,
        "created_at": _NOW,
        "updated_at": _NOW,
        "deleted_at": None,
        "my_permissions": _PERM_WRITE,
        "valued_secrets_count": 0,
        "placeholder_secrets_count": 0,
    }
)


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


def _make_pool() -> MagicMock:
    """Pool avec conn qui retourne user puis wallet sur fetchrow successifs."""
    conn = MagicMock()
    # Premier fetchrow → user row (get_by_keycloak_sub)
    # Deuxième fetchrow → wallet row (get_wallet_for_user)
    conn.fetchrow = AsyncMock(side_effect=[_USER_ROW, _WALLET_ROW])
    # fetch → tags vides
    conn.fetch = AsyncMock(return_value=[])

    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


@pytest.mark.asyncio
async def test_post_secret_with_trailing_slash_returns_400_invalid_secret_path() -> None:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = _make_pool()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={"name": "/foo/bar/", "encrypted_value": _FAKE_ENC_VALUE},
            headers={"Authorization": f"Bearer {make_jwt_token()}"},
        )

    assert r.status_code == 400, r.text
    body = r.json()
    assert body.get("error") == "invalid_secret_path"
    assert "trailing" in body.get("message", "").lower()


@pytest.mark.asyncio
async def test_post_secret_with_double_slash_returns_400_invalid_secret_path() -> None:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = _make_pool()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={"name": "/foo//bar", "encrypted_value": _FAKE_ENC_VALUE},
            headers={"Authorization": f"Bearer {make_jwt_token()}"},
        )

    assert r.status_code == 400, r.text
    assert r.json().get("error") == "invalid_secret_path"
