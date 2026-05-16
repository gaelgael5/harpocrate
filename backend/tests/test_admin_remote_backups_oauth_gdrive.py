"""Tests des endpoints /v1/admin/backup-remotes/oauth/gdrive/*."""

from __future__ import annotations

import base64
import datetime
from typing import Any
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

# ─── Helpers (calqués sur test_admin_remote_backups_test_returns_patch.py) ───


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "test-client")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://example.com")
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


# ─── Tests GET /redirect-uri ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redirect_uri_returns_canonical_value() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get(
            "/v1/admin/backup-remotes/oauth/gdrive/redirect-uri",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["redirect_uri"].endswith("/v1/admin/backup-remotes/oauth/gdrive/callback")


@pytest.mark.asyncio
async def test_redirect_uri_requires_admin() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/backup-remotes/oauth/gdrive/redirect-uri")
    assert r.status_code in (401, 403)


# ─── Tests POST /start ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oauth_start_creates_pending_and_returns_auth_url() -> None:
    async def _fake_create_pending(
        conn: Any,
        *,
        name: str,
        client_id: str,
        client_secret: str,
        folder_name: str,
        redirect_uri: str,
        target_connection_id: Any,
        created_by_user_id: Any,
    ) -> dict[str, str]:
        return {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?state=STATE-X",
            "state": "STATE-X",
        }

    from app.services import gdrive_oauth_session as svc_mod

    orig = svc_mod.create_pending_session
    svc_mod.create_pending_session = _fake_create_pending  # type: ignore[assignment]
    try:
        conn = MagicMock()
        async with _client(_make_pool(conn)) as cli:
            r = await cli.post(
                "/v1/admin/backup-remotes/oauth/gdrive/start",
                json={
                    "name": "Backups perso",
                    "client_id": "cid.apps.googleusercontent.com",
                    "client_secret": "GOCSPX-fake",
                    "folder_name": "Harpocrate Backups",
                },
                headers=_admin_header(),
            )
    finally:
        svc_mod.create_pending_session = orig  # type: ignore[assignment]

    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "STATE-X"
    assert body["auth_url"].startswith("https://accounts.google.com/")


@pytest.mark.asyncio
async def test_oauth_start_validates_required_fields() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/backup-remotes/oauth/gdrive/start",
            json={"name": "X"},  # manque client_id/secret/folder
            headers=_admin_header(),
        )
    assert r.status_code == 422
