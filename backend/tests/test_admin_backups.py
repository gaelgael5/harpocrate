"""Tests des endpoints /v1/admin/backups/* — LOT_12A."""
from __future__ import annotations

import base64
import datetime
import json
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_ADMIN_ROLE = "harpocrate-admin"
_BACKUP_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


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


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(
        extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}, "email": "admin@test.com"}
    )
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


class FakeRecord(dict):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


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


def _fake_backup_row() -> FakeRecord:
    return FakeRecord({
        "id": _BACKUP_ID,
        "filename": "harpocrate-backup-2026-01-01-12-00-00.tar.age",
        "size_bytes": 123456,
        "checksum_sha256": "deadbeef",
        "age_recipient": "age1qyq...",
        "manifest": json.dumps({
            "format_version": "1",
            "harpocrate_version": "0.1.0",
            "created_at": _NOW.isoformat() + "Z",
            "created_by": {"user_id": str(_USER_ID), "email": "admin@test.com"},
            "description": "test backup",
            "checksums": {},
            "stats": {"users_count": 1},
            "age_recipient": "age1qyq...",
            "schema_version": "001",
            "session_epoch_at_backup": 1,
        }),
        "description": "test backup",
        "created_at": _NOW,
        "created_by_user_id": _USER_ID,
        "imported": False,
    })


@pytest.mark.asyncio
async def test_list_backups_requires_admin() -> None:
    """GET /v1/admin/backups → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/backups", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_backups_empty() -> None:
    """GET /v1/admin/backups → 200 liste vide."""
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/backups", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["backups"] == []


@pytest.mark.asyncio
async def test_list_backups_with_results() -> None:
    """GET /v1/admin/backups → 200 avec backup."""
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[_fake_backup_row()])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/backups", headers=_admin_header())
    assert r.status_code == 200
    backups = r.json()["backups"]
    assert len(backups) == 1
    assert backups[0]["filename"] == "harpocrate-backup-2026-01-01-12-00-00.tar.age"


@pytest.mark.asyncio
async def test_get_backup_not_found() -> None:
    """GET /v1/admin/backups/{id} → 404 si absent."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/admin/backups/{_BACKUP_ID}", headers=_admin_header())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_backup_found() -> None:
    """GET /v1/admin/backups/{id} → 200 avec détails."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_backup_row())

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/admin/backups/{_BACKUP_ID}", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["id"] == str(_BACKUP_ID)


@pytest.mark.asyncio
async def test_create_backup_requires_admin() -> None:
    """POST /v1/admin/backups → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/backups",
            json={"description": "test"},
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_backup_not_found() -> None:
    """DELETE /v1/admin/backups/{id} → 404 si absent."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/backups/{_BACKUP_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restore_wrong_confirmation() -> None:
    """POST /v1/admin/backups/{id}/restore → 400 si confirmation incorrecte."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_backup_row())

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/restore",
            json={
                "age_private_key": "AGE-SECRET-KEY-1...",
                "confirmation": "WRONG CONFIRMATION",
                "auto_enable_maintenance": False,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "wrong_confirmation"
