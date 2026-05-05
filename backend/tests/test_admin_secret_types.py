"""Tests des endpoints /v1/admin/secret-types/* — LOT_15."""
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
_TYPE_UUID = uuid.uuid4()
_VERSION_UUID = uuid.uuid4()


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
    conn.execute = AsyncMock(return_value="UPDATE 1")

    class _Tx:
        async def __aenter__(self) -> None:
            pass

        async def __aexit__(self, *a: Any) -> None:
            pass

    conn.transaction = MagicMock(return_value=_Tx())
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


def _make_type_record(
    type_uuid: uuid.UUID | None = None,
    is_system: bool = False,
    used_count: int = 0,
    deprecated_at: datetime.datetime | None = None,
    current_version_uuid: uuid.UUID | None = None,
) -> MagicMock:
    r = MagicMock()
    r.__getitem__ = lambda self, k: {
        "type_uuid": type_uuid or _TYPE_UUID,
        "type": "aws",
        "sous_type": "credentials",
        "label": "AWS Credentials",
        "description": "Test desc",
        "is_system": is_system,
        "deprecated_at": deprecated_at,
        "current_version_uuid": current_version_uuid or _VERSION_UUID,
        "cv_version": 1,
        "cv_created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        "cv_schema_data": json.dumps({"type": "object", "properties": {}}),
        "cv_schema_ui": json.dumps({}),
        "cv_notes": None,
        "used_count": used_count,
    }[k]
    return r


def _make_version_record(
    version_uuid: uuid.UUID | None = None,
    parent_uuid: uuid.UUID | None = None,
) -> MagicMock:
    r = MagicMock()
    r.__getitem__ = lambda self, k: {
        "version_uuid": version_uuid or _VERSION_UUID,
        "parent_uuid": parent_uuid or _TYPE_UUID,
        "version": 1,
        "schema_data": json.dumps({"type": "object", "properties": {}}),
        "schema_ui": json.dumps({}),
        "notes": "Initial version",
        "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        "created_by_user_id": None,
    }[k]
    return r


_VALID_SCHEMA = {"type": "object", "properties": {"key": {"type": "string"}}}


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_types_requires_admin() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/secret-types", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_types_empty() -> None:
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[])
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/secret-types", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["types"] == []


@pytest.mark.asyncio
async def test_create_type_requires_admin() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/secret-types",
            headers=_user_header(),
            json={"type": "aws", "sous_type": "creds", "schema_data": _VALID_SCHEMA},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_type_success() -> None:
    conn = _make_conn()
    # insert type_uuid returned
    conn.fetchrow = AsyncMock(
        side_effect=[
            MagicMock(**{"__getitem__": lambda self, k: _TYPE_UUID if k == "type_uuid" else _VERSION_UUID}),
            MagicMock(**{"__getitem__": lambda self, k: _VERSION_UUID}),
        ]
    )
    conn.execute = AsyncMock(return_value="UPDATE 1")
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/secret-types",
            headers=_admin_header(),
            json={
                "type": "aws",
                "sous_type": "credentials",
                "schema_data": _VALID_SCHEMA,
                "schema_ui": {},
                "notes": "Initial",
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert "type_uuid" in body
    assert "version_uuid" in body


@pytest.mark.asyncio
async def test_create_type_invalid_schema_400() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/secret-types",
            headers=_admin_header(),
            json={
                "type": "aws",
                "sous_type": "creds",
                "schema_data": {"type": "INVALID_TYPE_XYZ"},
            },
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_json_schema"


@pytest.mark.asyncio
async def test_get_type_not_found_404() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/admin/secret-types/{_TYPE_UUID}", headers=_admin_header()
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_type_returns_data() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_make_type_record())
    conn.fetch = AsyncMock(return_value=[_make_version_record()])
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/admin/secret-types/{_TYPE_UUID}", headers=_admin_header()
        )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "aws"
    assert body["sous_type"] == "credentials"
    assert "all_versions" in body
    assert len(body["all_versions"]) == 1


@pytest.mark.asyncio
async def test_delete_type_not_found_404() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/secret-types/{_TYPE_UUID}", headers=_admin_header()
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_system_type_403() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_make_type_record(is_system=True))
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/secret-types/{_TYPE_UUID}", headers=_admin_header()
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_type_in_use_409() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_make_type_record(used_count=3))
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/secret-types/{_TYPE_UUID}", headers=_admin_header()
        )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "secret_type_in_use"


@pytest.mark.asyncio
async def test_validate_schema_valid() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/secret-types/validate-schema",
            headers=_admin_header(),
            json={"schema_data": _VALID_SCHEMA},
        )
    assert r.status_code == 200
    assert r.json()["valid"] is True


@pytest.mark.asyncio
async def test_validate_schema_invalid() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/secret-types/validate-schema",
            headers=_admin_header(),
            json={"schema_data": {"type": "NOTAVALIDTYPE"}},
        )
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert "error" in r.json()


@pytest.mark.asyncio
async def test_add_version_success() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(
        side_effect=[
            _make_type_record(),
            MagicMock(**{"__getitem__": lambda self, k: _VERSION_UUID}),
        ]
    )
    conn.fetchval = AsyncMock(return_value=1)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/secret-types/{_TYPE_UUID}/schemas",
            headers=_admin_header(),
            json={"schema_data": _VALID_SCHEMA, "set_as_current": True},
        )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_delete_current_version_409() -> None:
    conn = _make_conn()
    ver_rec = _make_version_record()
    type_rec = _make_type_record(current_version_uuid=_VERSION_UUID)
    conn.fetchrow = AsyncMock(side_effect=[ver_rec, type_rec])
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/secret-types/{_TYPE_UUID}/schemas/{_VERSION_UUID}",
            headers=_admin_header(),
        )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_public_list_types_requires_jwt() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/secret-types")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_public_list_types_returns_list() -> None:
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[])
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/secret-types", headers=_user_header())
    assert r.status_code == 200
    assert "types" in r.json()
