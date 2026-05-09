"""Tests des endpoints /v1/admin/backup-remotes."""

from __future__ import annotations

import base64
import datetime
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CONN_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")


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
    """Forge un JWT admin local HS256 valide pour les tests (rôle harpocrate-admin)."""
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
    # HS256 utilise HMAC_KEY directement (pas de derivation)
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


def _fake_dto_dict() -> dict[str, Any]:
    return {
        "id": str(_CONN_ID),
        "name": "OVH backup",
        "kind": "sftp",
        "config": {"host": "sftp.test", "port": 22, "remote_path": "/backups"},
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
        "created_by_user_id": None,
        "deleted_at": None,
    }


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_admin() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/backup-remotes")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_returns_connections_without_credentials() -> None:
    from app.services import remote_backup_connections as svc

    fake_dto = MagicMock()
    fake_dto.to_dict = MagicMock(return_value=_fake_dto_dict())

    async def fake_list(conn: Any) -> list[Any]:
        return [fake_dto]

    original = svc.list_connections
    svc.list_connections = fake_list  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.get("/v1/admin/backup-remotes", headers=_admin_header())
    finally:
        svc.list_connections = original  # type: ignore[assignment]

    assert r.status_code == 200, r.text
    body = r.json()
    serialized = json.dumps(body)
    # Vérifier qu'aucune trace de credentials
    assert "credentials" not in serialized
    assert "password" not in serialized
    assert "private_key" not in serialized
    assert body["connections"][0]["name"] == "OVH backup"


@pytest.mark.asyncio
async def test_create_returns_id_and_calls_service_with_credentials() -> None:
    from app.services import remote_backup_connections as svc

    captured: dict[str, Any] = {}

    async def fake_create(
        conn: Any,
        *,
        name: str,
        kind: str,
        config: dict,
        credentials: dict,
        created_by_user_id: Any,
    ) -> uuid.UUID:
        captured["name"] = name
        captured["kind"] = kind
        captured["config"] = config
        captured["credentials"] = credentials
        return _CONN_ID

    original = svc.create_connection
    svc.create_connection = fake_create  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(
                "/v1/admin/backup-remotes",
                headers=_admin_header(),
                json={
                    "name": "OVH",
                    "kind": "sftp",
                    "config": {"host": "h", "port": 22, "remote_path": "/x"},
                    "credentials": {"username": "u", "password": "p"},
                },
            )
    finally:
        svc.create_connection = original  # type: ignore[assignment]

    assert r.status_code == 201, r.text
    assert r.json() == {"id": str(_CONN_ID)}
    assert captured["credentials"] == {"username": "u", "password": "p"}


@pytest.mark.asyncio
async def test_create_rejects_unknown_kind() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/backup-remotes",
            headers=_admin_header(),
            json={
                "name": "X",
                "kind": "azure-blob",  # pas supporté
                "config": {},
                "credentials": {},
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_returns_404_if_not_found() -> None:
    from app.services import remote_backup_connections as svc

    async def fake_get(conn: Any, cid: uuid.UUID) -> Any:
        return None

    original = svc.get_connection
    svc.get_connection = fake_get  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.get(f"/v1/admin/backup-remotes/{_CONN_ID}", headers=_admin_header())
    finally:
        svc.get_connection = original  # type: ignore[assignment]

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_test_endpoint_returns_ok_on_success() -> None:
    from app.services import remote_backup_connections as svc
    from app.services import remote_backup_providers as providers

    fake_dto = MagicMock()
    fake_dto.kind = "sftp"
    fake_dto.config = {"host": "h", "port": 22, "remote_path": "/x"}
    fake_dto.to_dict = MagicMock(return_value=_fake_dto_dict())

    async def fake_get(conn: Any, cid: uuid.UUID) -> Any:
        return fake_dto

    async def fake_get_creds(conn: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    fake_provider = MagicMock()
    fake_provider.test_connection = AsyncMock(return_value=None)

    def fake_get_provider(kind: str, config: dict, credentials: dict) -> Any:
        return fake_provider

    orig_get = svc.get_connection
    orig_creds = svc.get_decrypted_credentials
    orig_factory = providers.get_provider
    svc.get_connection = fake_get  # type: ignore[assignment]
    svc.get_decrypted_credentials = fake_get_creds  # type: ignore[assignment]
    # Monkey-patch the import inside admin_remote_backups
    from app.api.v1 import admin_remote_backups as ar

    ar.get_provider = fake_get_provider  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(f"/v1/admin/backup-remotes/{_CONN_ID}/test", headers=_admin_header())
    finally:
        svc.get_connection = orig_get  # type: ignore[assignment]
        svc.get_decrypted_credentials = orig_creds  # type: ignore[assignment]
        ar.get_provider = orig_factory  # type: ignore[assignment]

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_test_endpoint_returns_200_with_ok_false_on_provider_error() -> None:
    from app.services import remote_backup_connections as svc
    from app.services.remote_backup_providers import (
        RemoteBackupProviderError,
    )

    fake_dto = MagicMock()
    fake_dto.kind = "sftp"
    fake_dto.config = {"host": "h", "port": 22, "remote_path": "/x"}

    async def fake_get(conn: Any, cid: uuid.UUID) -> Any:
        return fake_dto

    async def fake_get_creds(conn: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    fake_provider = MagicMock()
    fake_provider.test_connection = AsyncMock(
        side_effect=RemoteBackupProviderError("Connection refused")
    )

    def fake_get_provider(kind: str, config: dict, credentials: dict) -> Any:
        return fake_provider

    orig_get = svc.get_connection
    orig_creds = svc.get_decrypted_credentials
    svc.get_connection = fake_get  # type: ignore[assignment]
    svc.get_decrypted_credentials = fake_get_creds  # type: ignore[assignment]
    from app.api.v1 import admin_remote_backups as ar

    orig_factory = ar.get_provider
    ar.get_provider = fake_get_provider  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(f"/v1/admin/backup-remotes/{_CONN_ID}/test", headers=_admin_header())
    finally:
        svc.get_connection = orig_get  # type: ignore[assignment]
        svc.get_decrypted_credentials = orig_creds  # type: ignore[assignment]
        ar.get_provider = orig_factory  # type: ignore[assignment]

    # 200 + ok:false : la requête HTTP a abouti, le résultat (négatif) est dans
    # le body. Évite que Cloudflare avale un 5xx et masque le message d'erreur.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "test_failed"
    assert "Connection refused" in body["message"]


@pytest.mark.asyncio
async def test_delete_returns_204_on_success() -> None:
    from app.services import remote_backup_connections as svc

    async def fake_delete(conn: Any, cid: uuid.UUID) -> int:
        return 1

    original = svc.delete_connection
    svc.delete_connection = fake_delete  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.delete(f"/v1/admin/backup-remotes/{_CONN_ID}", headers=_admin_header())
    finally:
        svc.delete_connection = original  # type: ignore[assignment]

    assert r.status_code == 204
