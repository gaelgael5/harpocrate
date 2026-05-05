"""Tests P4 — GET /by-path/count + DELETE /by-path (suppression récursive de dossier)."""
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


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


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


def _user_row() -> FakeRecord:
    return FakeRecord({
        "id": _CALLER_ID, "keycloak_sub": "test-sub-001", "email": "alice@example.com",
        "display_name": "Alice", "rsa_public_key": b"x", "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16, "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x", "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536, "kdf_iterations": 3, "kdf_parallelism": 4,
        "rsa_key_size": 2048, "created_at": _NOW, "updated_at": _NOW,
        "last_unlock_at": None,
    })


def _wallet_row(permissions: int = 63) -> FakeRecord:
    return FakeRecord({
        "id": _WALLET_ID, "name": "W", "description": None,
        "owner_user_id": _CALLER_ID, "created_at": _NOW, "updated_at": _NOW,
        "my_permissions": permissions, "valued_secrets_count": 0,
        "placeholder_secrets_count": 0, "deleted_at": None,
    })


class _Tx:
    async def __aenter__(self) -> _Tx: return self
    async def __aexit__(self, *a: Any) -> None: pass


def _conn() -> MagicMock:
    c: MagicMock = MagicMock()
    c.fetchrow = AsyncMock(return_value=None)
    c.fetchval = AsyncMock(return_value=None)
    c.fetch = AsyncMock(return_value=[])
    c.execute = AsyncMock(return_value=None)
    c.transaction = MagicMock(return_value=_Tx())
    return c


def _pool(conn: MagicMock) -> MagicMock:
    class _A:
        async def __aenter__(self) -> MagicMock: return conn
        async def __aexit__(self, *a: Any) -> None: pass
    p = MagicMock()
    p.acquire = MagicMock(return_value=_A())
    return p


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pm
    from app.main import app
    pm._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _hdr() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


@pytest.mark.asyncio
async def test_count_by_path_returns_count() -> None:
    """GET /by-path/count?path=/foo/ → {count: N}"""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        return None

    conn.fetchrow = fr
    conn.fetchval = AsyncMock(return_value=7)  # COUNT result

    async with _client(_pool(conn)) as cli:
        r = await cli.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-path/count",
            params={"path": "/users/foo/"},
            headers=_hdr(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"count": 7}


@pytest.mark.asyncio
async def test_delete_by_path_returns_deleted_count() -> None:
    """DELETE /by-path?path=/foo/ → {deleted: N}, exécute le DELETE SQL."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        return None

    deleted_rows = [
        FakeRecord({"id": uuid.uuid4(), "name": "/users/foo/key1"}),
        FakeRecord({"id": uuid.uuid4(), "name": "/users/foo/key2"}),
        FakeRecord({"id": uuid.uuid4(), "name": "/users/foo/sub/key3"}),
    ]

    async def fetch_side(query: str, *args: Any) -> list[Any]:
        # Route: wallet tags fetch returns [] (no tags on wallet),
        # DELETE RETURNING fetch returns the deleted_rows (identified by RETURNING clause)
        if "RETURNING" in query:
            return deleted_rows
        return []

    conn.fetchrow = fr
    conn.fetch = fetch_side

    async with _client(_pool(conn)) as cli:
        r = await cli.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-path",
            params={"path": "/users/foo/"},
            headers=_hdr(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 3}


@pytest.mark.asyncio
async def test_delete_by_path_root_refused() -> None:
    """DELETE /by-path?path=/ → 400 cannot_delete_root_path."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        return None

    conn.fetchrow = fr

    async with _client(_pool(conn)) as cli:
        r = await cli.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-path",
            params={"path": "/"},
            headers=_hdr(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_delete_root_path"
