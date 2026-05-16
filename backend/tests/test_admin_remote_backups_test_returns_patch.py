"""Le retour de test_connection (patch config) est exposé dans la réponse."""

from __future__ import annotations

import base64
import datetime
import uuid
from typing import Any
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

# ─── Helpers copiés du pattern test_admin_remote_backups.py ──────────────────

_CONN_ID = uuid.UUID("22222222-0000-0000-0000-000000000001")


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


def _admin_jwt() -> str:
    """Forge un JWT admin local HS256 valide pour les tests."""
    from app.core.config import settings

    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    payload = {
        "sub": "admin",
        "email": "admin@test",
        "name": "Admin",
        "iat": now,
        "exp": now + 3600,
        "iss": "harpocrate-local",
        "aud": settings.keycloak_client_id,
        "realm_access": {"roles": [settings.admin_role_name]},
    }
    secret = base64.b64decode(settings.hmac_key)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_jwt()}"}


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── Tests POST /test (credentials fournis dans le body) ─────────────────────


@pytest.mark.asyncio
async def test_test_endpoint_returns_config_patch() -> None:
    """L'endpoint POST /test inclut config_patch quand le provider retourne un dict."""

    class _FakeProvider:
        def __init__(self, **_: object) -> None: ...

        async def test_connection(self, path: str) -> dict[str, Any]:
            return {"folder_id": "abc123"}

        async def upload_stream(self, *_a: object, **_kw: object) -> None: ...

    def _fake_get_provider(kind: str, config: dict, credentials: dict) -> _FakeProvider:
        return _FakeProvider()

    from app.api.v1 import admin_remote_backups as ar

    orig_factory = ar.get_provider
    ar.get_provider = _fake_get_provider  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(
                "/v1/admin/backup-remotes/test",
                json={
                    "kind": "sftp",
                    "config": {"host": "h"},
                    "credentials": {"username": "u", "auth_method": "password", "password": "p"},
                    "path": "/x",
                },
                headers=_admin_header(),
            )
    finally:
        ar.get_provider = orig_factory  # type: ignore[assignment]

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("config_patch") == {"folder_id": "abc123"}


@pytest.mark.asyncio
async def test_test_endpoint_no_patch_when_provider_returns_none() -> None:
    """Le helper n'expose pas config_patch quand le provider retourne None."""

    class _FakeProvider:
        def __init__(self, **_: object) -> None: ...

        async def test_connection(self, path: str) -> None:
            return None

        async def upload_stream(self, *_a: object, **_kw: object) -> None: ...

    def _fake_get_provider(kind: str, config: dict, credentials: dict) -> _FakeProvider:
        return _FakeProvider()

    from app.api.v1 import admin_remote_backups as ar

    orig_factory = ar.get_provider
    ar.get_provider = _fake_get_provider  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(
                "/v1/admin/backup-remotes/test",
                json={
                    "kind": "sftp",
                    "config": {"host": "h"},
                    "credentials": {"username": "u", "auth_method": "password", "password": "p"},
                    "path": "/x",
                },
                headers=_admin_header(),
            )
    finally:
        ar.get_provider = orig_factory  # type: ignore[assignment]

    body = r.json()
    assert body["ok"] is True
    assert "config_patch" not in body or body["config_patch"] is None


# ─── Tests POST /{connection_id}/test (credentials stockés) ──────────────────


@pytest.mark.asyncio
async def test_stored_test_endpoint_returns_config_patch_and_persists() -> None:
    """POST /{id}/test : config_patch retourné ET persisté via svc.update_connection."""
    from app.services import remote_backup_connections as svc

    fake_dto = MagicMock()
    fake_dto.kind = "sftp"
    fake_dto.config = {"host": "h", "port": 22}

    update_calls: list[dict[str, Any]] = []

    async def fake_get(conn: Any, cid: uuid.UUID) -> Any:
        return fake_dto

    async def fake_get_creds(conn: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    async def fake_update(
        conn: Any,
        *,
        connection_id: uuid.UUID,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
    ) -> int:
        update_calls.append({"connection_id": connection_id, "config": config})
        return 1

    class _FakeProvider:
        def __init__(self, **_: object) -> None: ...

        async def test_connection(self, path: str) -> dict[str, Any]:
            return {"folder_id": "discovered_folder"}

        async def upload_stream(self, *_a: object, **_kw: object) -> None: ...

    def _fake_get_provider(kind: str, config: dict, credentials: dict) -> _FakeProvider:
        return _FakeProvider()

    from app.api.v1 import admin_remote_backups as ar

    orig_get = svc.get_connection
    orig_creds = svc.get_decrypted_credentials
    orig_update = svc.update_connection
    orig_factory = ar.get_provider

    svc.get_connection = fake_get  # type: ignore[assignment]
    svc.get_decrypted_credentials = fake_get_creds  # type: ignore[assignment]
    svc.update_connection = fake_update  # type: ignore[assignment]
    ar.get_provider = _fake_get_provider  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(
                f"/v1/admin/backup-remotes/{_CONN_ID}/test",
                json={"path": "/snapshots"},
                headers=_admin_header(),
            )
    finally:
        svc.get_connection = orig_get  # type: ignore[assignment]
        svc.get_decrypted_credentials = orig_creds  # type: ignore[assignment]
        svc.update_connection = orig_update  # type: ignore[assignment]
        ar.get_provider = orig_factory  # type: ignore[assignment]

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("config_patch") == {"folder_id": "discovered_folder"}
    # Le patch doit avoir été persisté (merger avec config existant)
    assert len(update_calls) == 1
    assert update_calls[0]["config"] == {"host": "h", "port": 22, "folder_id": "discovered_folder"}


@pytest.mark.asyncio
async def test_stored_test_endpoint_no_update_when_no_patch() -> None:
    """POST /{id}/test : aucun update_connection si le provider retourne None."""
    from app.services import remote_backup_connections as svc

    fake_dto = MagicMock()
    fake_dto.kind = "sftp"
    fake_dto.config = {"host": "h"}

    update_calls: list[Any] = []

    async def fake_get(conn: Any, cid: uuid.UUID) -> Any:
        return fake_dto

    async def fake_get_creds(conn: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    async def fake_update(conn: Any, *, connection_id: uuid.UUID, **_kw: Any) -> int:
        update_calls.append(connection_id)
        return 1

    class _FakeProvider:
        def __init__(self, **_: object) -> None: ...

        async def test_connection(self, path: str) -> None:
            return None

        async def upload_stream(self, *_a: object, **_kw: object) -> None: ...

    def _fake_get_provider(kind: str, config: dict, credentials: dict) -> _FakeProvider:
        return _FakeProvider()

    from app.api.v1 import admin_remote_backups as ar

    orig_get = svc.get_connection
    orig_creds = svc.get_decrypted_credentials
    orig_update = svc.update_connection
    orig_factory = ar.get_provider

    svc.get_connection = fake_get  # type: ignore[assignment]
    svc.get_decrypted_credentials = fake_get_creds  # type: ignore[assignment]
    svc.update_connection = fake_update  # type: ignore[assignment]
    ar.get_provider = _fake_get_provider  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(
                f"/v1/admin/backup-remotes/{_CONN_ID}/test",
                json={"path": "/snapshots"},
                headers=_admin_header(),
            )
    finally:
        svc.get_connection = orig_get  # type: ignore[assignment]
        svc.get_decrypted_credentials = orig_creds  # type: ignore[assignment]
        svc.update_connection = orig_update  # type: ignore[assignment]
        ar.get_provider = orig_factory  # type: ignore[assignment]

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Aucun appel à update_connection quand le patch est None
    assert len(update_calls) == 0
