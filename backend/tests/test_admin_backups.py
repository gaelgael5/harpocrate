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


# ─── LOT 13 — S3 endpoints ───────────────────────────────────────────────────


# ─── LOT L3 — Push to remote (SFTP) ──────────────────────────────────────────


_REMOTE_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")


def _fake_remote_dto(*, with_full_path: bool = True) -> Any:
    """DTO RemoteBackupConnection mocké (ne contient JAMAIS les credentials)."""
    dto = MagicMock()
    dto.id = _REMOTE_ID
    dto.name = "OVH backup"
    dto.kind = "sftp"
    config: dict[str, Any] = {"host": "sftp.test", "port": 22}
    if with_full_path:
        config["remote_path_full"] = "/backups/full"
    dto.config = config
    return dto


@pytest.mark.asyncio
async def test_push_remote_requires_admin() -> None:
    """POST /v1/admin/backups/{id}/push-to-remote/{rid} → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_push_remote_backup_not_found() -> None:
    """POST .../push-to-remote/... → 404 si backup absent."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "backup_not_found"


@pytest.mark.asyncio
async def test_push_remote_remote_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST .../push-to-remote/... → 404 si la connexion remote est absente."""
    from app.services import remote_backup_connections as remote_svc

    async def _no_conn(c: Any, cid: uuid.UUID) -> Any:
        return None

    monkeypatch.setattr(remote_svc, "get_connection", _no_conn)

    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_backup_row())
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "remote_not_found"


@pytest.mark.asyncio
async def test_push_remote_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """POST .../push-to-remote/... → 404 si le fichier backup n'existe plus sur disque."""
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))

    async def _ok_conn(c: Any, cid: uuid.UUID) -> Any:
        return _fake_remote_dto()

    async def _ok_creds(c: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _ok_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _ok_creds)

    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_backup_row())
    # le tmp_path est vide → file_missing
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "file_missing"


@pytest.mark.asyncio
async def test_push_remote_provider_error_returns_422(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """POST .../push-to-remote/... → 422 si le provider lève RemoteBackupProviderError.

    On retourne 422 (Unprocessable Entity) plutôt que 502 (Bad Gateway) pour que
    Cloudflare laisse passer le payload `detail.message` au client (Cloudflare
    intercepte les 502/504 avec son écran d'erreur générique).
    """
    from app.api.v1 import admin_backups as ab
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc
    from app.services.remote_backup_providers import RemoteBackupProviderError

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))
    fake = _fake_backup_row()
    (tmp_path / fake["filename"]).write_bytes(b"backup-bytes")

    async def _ok_conn(c: Any, cid: uuid.UUID) -> Any:
        return _fake_remote_dto()

    async def _ok_creds(c: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _ok_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _ok_creds)

    fake_provider = MagicMock()
    fake_provider.upload_stream = AsyncMock(
        side_effect=RemoteBackupProviderError("connection refused")
    )
    monkeypatch.setattr(ab, "get_provider", lambda *_a, **_kw: fake_provider)

    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=fake)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["error"] == "remote_push_failed"
    assert "connection refused" in body["detail"]["message"]


@pytest.mark.asyncio
async def test_push_remote_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """POST .../push-to-remote/... → 202 avec bytes_sent + remote_filename."""
    from app.api.v1 import admin_backups as ab
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))
    fake = _fake_backup_row()
    payload = b"x" * (128 * 1024 + 7)  # > 1 chunk pour exercer le streaming
    (tmp_path / fake["filename"]).write_bytes(payload)

    async def _ok_conn(c: Any, cid: uuid.UUID) -> Any:
        return _fake_remote_dto()

    async def _ok_creds(c: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _ok_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _ok_creds)

    captured: dict[str, Any] = {}

    async def _consume(target_path: str, remote_filename: str, source: Any) -> int:
        captured["target_path"] = target_path
        captured["filename"] = remote_filename
        total = 0
        async for chunk in source:
            total += len(chunk)
        return total

    fake_provider = MagicMock()
    fake_provider.upload_stream = AsyncMock(side_effect=_consume)
    monkeypatch.setattr(ab, "get_provider", lambda *_a, **_kw: fake_provider)

    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=fake)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["remote_id"] == str(_REMOTE_ID)
    assert body["remote_name"] == "OVH backup"
    assert body["remote_filename"] == fake["filename"]
    assert body["bytes_sent"] == len(payload)
    assert captured["filename"] == fake["filename"]
    assert captured["target_path"] == "/backups/full"


@pytest.mark.asyncio
async def test_push_remote_returns_422_when_no_full_path_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """POST .../push-to-remote/... → 422 si la connexion n'a pas de remote_path_full."""
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))
    fake = _fake_backup_row()
    (tmp_path / fake["filename"]).write_bytes(b"x")

    async def _ok_conn(c: Any, cid: uuid.UUID) -> Any:
        # connexion sans remote_path_full configuré
        return _fake_remote_dto(with_full_path=False)

    async def _ok_creds(c: Any, cid: uuid.UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _ok_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _ok_creds)

    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=fake)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/push-to-remote/{_REMOTE_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_full_path_configured"
