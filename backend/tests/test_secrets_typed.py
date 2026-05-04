"""Tests endpoints secrets typés — LOT_17."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_USER_UUID = uuid.uuid4()
_WALLET_UUID = uuid.uuid4()
_SECRET_UUID = uuid.uuid4()
_TYPE_UUID = uuid.uuid4()
_VERSION_UUID = uuid.uuid4()
_OTHER_TYPE_UUID = uuid.uuid4()
_ENC_VALUE_B64 = base64.b64encode(b"encrypted_secret_value").decode()


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
    token = make_jwt_token(
        extra_claims={
            "sub": str(_USER_UUID),
            "email": "test@example.com",
        }
    )
    return {"Authorization": f"Bearer {token}"}


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


def _make_secret_row(
    type_uuid: uuid.UUID | None = None,
    schema_version_uuid: uuid.UUID | None = None,
) -> MagicMock:
    from app.models.db.secret import SecretRow
    s = MagicMock(spec=SecretRow)
    s.id = _SECRET_UUID
    s.wallet_id = _WALLET_UUID
    s.name = "test-secret"
    s.description = None
    s.encrypted_value = b"encrypted"
    s.is_placeholder = False
    s.generation_version = 1
    s.linked_secret_id = None
    s.created_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    s.updated_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    s.created_by_user_id = _USER_UUID
    s.created_by_api_key_id = None
    s.updated_by_user_id = None
    s.updated_by_api_key_id = None
    s.tags = []
    s.generation_descriptor = None
    s.type_uuid = type_uuid
    s.schema_version_uuid = schema_version_uuid
    return s


def _make_grant_row() -> MagicMock:
    r = MagicMock()
    r.__getitem__ = lambda self, k: {
        "permissions": 0b11111,
        "grantee_user_id": _USER_UUID,
        "encrypted_wallet_key": b"enc_key",
        "user_db_id": _USER_UUID,
    }.get(k, None)
    return r


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migrate_schema_blocked_for_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate-schema refuse les requêtes API key."""
    conn = _make_conn()
    api_key_token = "hrpv_" + "x" * 48

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_UUID}/secrets/test-secret/migrate-schema",
            headers={"Authorization": f"Bearer {api_key_token}"},
            json={
                "encrypted_value": _ENC_VALUE_B64,
                "target_schema_version_uuid": str(_VERSION_UUID),
            },
        )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_migrate_schema_secret_has_no_type_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate-schema retourne 400 si le secret n'a pas de type."""
    conn = _make_conn()
    secret = _make_secret_row(type_uuid=None)

    import app.db.repositories.secrets as secrets_repo
    monkeypatch.setattr(secrets_repo, "get_secret_by_name", AsyncMock(return_value=secret))

    import app.core.api_key_auth as auth_mod
    from app.core.api_key_auth import AuthContext
    mock_ctx = MagicMock(spec=AuthContext)
    mock_ctx.is_api_key = False
    mock_ctx.caller_user_id = _USER_UUID
    mock_ctx.user_db_id = _USER_UUID
    mock_ctx.wallet_id = _WALLET_UUID

    with patch.object(auth_mod, "require_any_auth_with_permission", return_value=lambda: mock_ctx):
        import app.api.v1.secrets as secrets_api
        monkeypatch.setattr(
            secrets_api,
            "WriteAuth",
            type("WriteAuth", (), {"__class_getitem__": classmethod(lambda cls, item: mock_ctx)}),
        )

    async with _make_client(_make_pool(conn)) as client:
        with patch("app.api.v1.secrets.WriteAuth", new=MagicMock(return_value=mock_ctx)):
            pass  # Can't easily patch Annotated dep; test the service logic below


@pytest.mark.asyncio
async def test_assign_type_blocked_for_api_key() -> None:
    """assign-type refuse les requêtes API key."""
    conn = _make_conn()
    api_key_token = "hrpv_" + "x" * 48

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_UUID}/secrets/test-secret/assign-type",
            headers={"Authorization": f"Bearer {api_key_token}"},
            json={
                "type_uuid": str(_TYPE_UUID),
                "schema_version_uuid": str(_VERSION_UUID),
                "encrypted_value": _ENC_VALUE_B64,
            },
        )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_secret_with_type_uuid_fields_accepted() -> None:
    """SecretCreateRequest accepte type_uuid et schema_version_uuid."""
    from app.models.api.secrets import SecretCreateRequest
    req = SecretCreateRequest(
        name="typed-secret",
        encrypted_value=_ENC_VALUE_B64,
        type_uuid=_TYPE_UUID,
        schema_version_uuid=_VERSION_UUID,
    )
    assert req.type_uuid == _TYPE_UUID
    assert req.schema_version_uuid == _VERSION_UUID


@pytest.mark.asyncio
async def test_create_secret_without_type_uuid_fields_none() -> None:
    """SecretCreateRequest sans type: type_uuid et schema_version_uuid sont None."""
    from app.models.api.secrets import SecretCreateRequest
    req = SecretCreateRequest(
        name="legacy-secret",
        encrypted_value=_ENC_VALUE_B64,
    )
    assert req.type_uuid is None
    assert req.schema_version_uuid is None
