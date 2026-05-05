"""Tests P1.5 — Auto-résolution du type RAW + rejet des types deprecated à la création."""
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
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_RAW_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
_RAW_VERSION_UUID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
_DEPRECATED_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
_DEPRECATED_VERSION_UUID = uuid.UUID("ffffffff-0000-0000-0000-000000000099")
_FAKE_ENC_VALUE = base64.b64encode(b"fake_encrypted_secret_value").decode()


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


def _fake_user_row() -> FakeRecord:
    return FakeRecord({
        "id": _CALLER_ID, "keycloak_sub": "test-sub-001", "email": "alice@example.com",
        "display_name": "Alice", "rsa_public_key": b"x", "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16, "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x", "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536, "kdf_iterations": 3, "kdf_parallelism": 4,
        "rsa_key_size": 2048, "created_at": _NOW, "updated_at": _NOW,
        "last_unlock_at": None,
    })


def _fake_wallet_row(permissions: int = 63) -> FakeRecord:
    return FakeRecord({
        "id": _WALLET_ID, "name": "Test Wallet", "description": None,
        "owner_user_id": _CALLER_ID, "created_at": _NOW, "updated_at": _NOW,
        "my_permissions": permissions, "valued_secrets_count": 0,
        "placeholder_secrets_count": 0, "deleted_at": None,
    })


def _fake_raw_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _RAW_TYPE_UUID,
        "current_version_uuid": _RAW_VERSION_UUID,
    })


def _fake_deprecated_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _DEPRECATED_TYPE_UUID,
        "current_version_uuid": _DEPRECATED_VERSION_UUID,
        "type": "old", "sous_type": "old", "label": None, "description": None,
        "is_system": False, "created_by_user_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "deprecated_at": _NOW,  # ← deprecated
        "cv_version": 1, "cv_schema_data": "{}", "cv_schema_ui": "{}",
        "cv_created_at": _NOW, "used_count": 0,
    })


def _fake_active_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _RAW_TYPE_UUID,
        "current_version_uuid": _RAW_VERSION_UUID,
        "type": "raw", "sous_type": "raw", "label": "Raw", "description": None,
        "is_system": True, "created_by_user_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "deprecated_at": None,
        "cv_version": 1, "cv_schema_data": "{}", "cv_schema_ui": "{}",
        "cv_created_at": _NOW, "used_count": 0,
    })


class _FakeTxCtx:
    async def __aenter__(self) -> _FakeTxCtx: return self
    async def __aexit__(self, *args: Any) -> None: pass


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    conn.executemany = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=_FakeTxCtx())
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock: return conn
        async def __aexit__(self, *args: Any) -> None: pass
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_secret_without_type_uuid_defaults_to_raw() -> None:
    """POST sans type_uuid → secret créé avec type_uuid = RAW.type_uuid + RAW current version."""
    conn = _make_conn()
    insert_args: list[Any] = []
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row()
        if "secret_types" in query and "raw" in query:
            return _fake_raw_type_row()
        return None

    async def fetchval_side(query: str, *args: Any) -> Any:
        if "INSERT INTO secrets" in query:
            insert_args.append(args)
            return _SECRET_ID
        return None

    conn.fetchrow = fetchrow_side
    conn.fetchval = fetchval_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={"name": "MY_KEY", "encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text
    # Vérifier que l'INSERT a bien reçu RAW type_uuid + RAW version_uuid
    assert insert_args, "INSERT INTO secrets jamais appelé"
    args = insert_args[0]
    # Signature: wallet_id, name, description, encrypted_value,
    # created_by_user_id, type_uuid, schema_version_uuid
    assert args[5] == _RAW_TYPE_UUID, f"type_uuid attendu RAW, reçu {args[5]}"
    assert args[6] == _RAW_VERSION_UUID, f"schema_version_uuid attendu RAW v1, reçu {args[6]}"


@pytest.mark.asyncio
async def test_post_secret_with_deprecated_type_uuid_returns_400() -> None:
    """POST avec un type_uuid deprecated → 400 invalid_type."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row()
        # 3e fetchrow : get_type sur le type deprecated
        if "secret_types" in query and "type_uuid" in query:
            return _fake_deprecated_type_row()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_KEY",
                "encrypted_value": _FAKE_ENC_VALUE,
                "type_uuid": str(_DEPRECATED_TYPE_UUID),
                "schema_version_uuid": str(_DEPRECATED_VERSION_UUID),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["error"] == "deprecated_type"


@pytest.mark.asyncio
async def test_post_secret_with_active_type_uuid_succeeds() -> None:
    """POST avec un type_uuid actif (non-deprecated) → 201."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row()
        if "secret_types" in query and "type_uuid" in query:
            return _fake_active_type_row()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetchval = AsyncMock(return_value=_SECRET_ID)
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_KEY",
                "encrypted_value": _FAKE_ENC_VALUE,
                "type_uuid": str(_RAW_TYPE_UUID),
                "schema_version_uuid": str(_RAW_VERSION_UUID),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text
