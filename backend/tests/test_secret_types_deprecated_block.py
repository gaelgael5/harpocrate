"""Tests P1.5 — Rejet 400 sur migrate-schema/assign-type vers un type deprecated."""

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
_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
_DEPRECATED_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
_TARGET_VERSION_UUID = uuid.UUID("ffffffff-0000-0000-0000-000000000099")
_FAKE_ENC = base64.b64encode(b"new").decode()


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
    return FakeRecord(
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
        }
    )


def _wallet_row() -> FakeRecord:
    return FakeRecord(
        {
            "id": _WALLET_ID,
            "name": "W",
            "description": None,
            "owner_user_id": _CALLER_ID,
            "created_at": _NOW,
            "updated_at": _NOW,
            "my_permissions": 63,
            "valued_secrets_count": 0,
            "placeholder_secrets_count": 0,
            "deleted_at": None,
        }
    )


def _secret_row(type_uuid: uuid.UUID = _TYPE_UUID) -> FakeRecord:
    return FakeRecord(
        {
            "id": _SECRET_ID,
            "wallet_id": _WALLET_ID,
            "name": "MY",
            "description": None,
            "encrypted_value": b"old",
            "is_placeholder": False,
            "generation_version": 1,
            "generation_descriptor": None,
            "linked_secret_id": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            "created_by_user_id": _CALLER_ID,
            "created_by_api_key_id": None,
            "updated_by_user_id": None,
            "updated_by_api_key_id": None,
            "type_uuid": type_uuid,
            "schema_version_uuid": None,
        }
    )


def _deprecated_type_row() -> FakeRecord:
    return FakeRecord(
        {
            "type_uuid": _DEPRECATED_TYPE_UUID,
            "current_version_uuid": _TARGET_VERSION_UUID,
            "type": "old",
            "sous_type": "old",
            "label": None,
            "description": None,
            "is_system": False,
            "created_by_user_id": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            "deprecated_at": _NOW,
            "cv_version": 1,
            "cv_schema_data": "{}",
            "cv_schema_ui": "{}",
            "cv_created_at": _NOW,
            "used_count": 0,
        }
    )


class _Tx:
    async def __aenter__(self) -> _Tx:
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass


def _conn() -> MagicMock:
    c: MagicMock = MagicMock()
    c.fetchrow = AsyncMock(return_value=None)
    c.fetchval = AsyncMock(return_value=None)
    c.fetch = AsyncMock(return_value=[])
    c.execute = AsyncMock(return_value=None)
    c.executemany = AsyncMock(return_value=None)
    c.transaction = MagicMock(return_value=_Tx())
    return c


def _pool(conn: MagicMock) -> MagicMock:
    class _A:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

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
async def test_migrate_schema_to_deprecated_type_returns_400() -> None:
    """PATCH /migrate-schema vers une version d'un type deprecated → 400."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        if "secret_schemas" in query and "version_uuid" in query and "parent_uuid" in query:
            # check du parent_uuid (dans migrate_schema existant)
            return FakeRecord({"parent_uuid": _DEPRECATED_TYPE_UUID})
        if "secret_types" in query and "type_uuid" in query:
            # nouveau check : on charge le type pour vérifier deprecated_at
            return _deprecated_type_row()
        if "secrets" in query.lower() and "wallet_id" in query and "name" in query:
            return _secret_row(type_uuid=_DEPRECATED_TYPE_UUID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _client(_pool(conn)) as cli:
        r = await cli.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY/migrate-schema",
            json={
                "encrypted_value": _FAKE_ENC,
                "target_schema_version_uuid": str(_TARGET_VERSION_UUID),
            },
            headers=_hdr(),
        )

    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "deprecated_type"


@pytest.mark.asyncio
async def test_assign_type_to_deprecated_type_returns_400() -> None:
    """PATCH /assign-type avec un type deprecated → 400."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        if "secret_schemas" in query and "version_uuid" in query and "parent_uuid" in query:
            return FakeRecord({"parent_uuid": _DEPRECATED_TYPE_UUID})
        if "secret_types" in query and "type_uuid" in query:
            return _deprecated_type_row()
        if "secrets" in query.lower() and "wallet_id" in query and "name" in query:
            return _secret_row(type_uuid=_TYPE_UUID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _client(_pool(conn)) as cli:
        r = await cli.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY/assign-type",
            json={
                "type_uuid": str(_DEPRECATED_TYPE_UUID),
                "schema_version_uuid": str(_TARGET_VERSION_UUID),
                "encrypted_value": _FAKE_ENC,
            },
            headers=_hdr(),
        )

    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "deprecated_type"
