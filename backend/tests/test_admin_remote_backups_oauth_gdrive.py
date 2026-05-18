"""Tests des endpoints /v1/admin/backup-remotes/oauth/gdrive/*."""

from __future__ import annotations

import base64
import datetime
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

# ─── Helpers (calqués sur test_admin_remote_backups_test_returns_patch.py) ───


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pas de réassignation de settings — voir test_admin_remote_backups.py:env()
    # pour le rationale (évite la pollution cross-fichiers via stale imports).
    import app.core.config

    settings = app.core.config.settings
    monkeypatch.setattr(settings, "keycloak_url", "https://kc.test")
    monkeypatch.setattr(settings, "keycloak_realm", "yoops")
    monkeypatch.setattr(settings, "keycloak_client_id", "test-client")
    monkeypatch.setattr(settings, "public_url", "https://example.com")
    monkeypatch.setattr(settings, "admin_local_enabled", True)
    monkeypatch.setattr(settings, "admin_local_username", "admin")
    monkeypatch.setattr(settings, "admin_local_password", "test-password")


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


@pytest.fixture
def admin_jwt_headers() -> dict[str, str]:
    return _admin_header()


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


@asynccontextmanager
async def _client(pool: MagicMock | None = None) -> Any:
    from app.db import pool as pool_mod
    from app.main import app

    if pool is not None:
        pool_mod._pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


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


# ─── Tests GET /callback ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oauth_callback_happy_path() -> None:
    """Happy path : code valide + state pending → postMessage ok=true."""
    from unittest.mock import AsyncMock, patch

    pending_row = {
        "state": "HAPPY",
        "status": "pending",
        "payload": {
            "client_id": "c",
            "client_secret": "s",
            "redirect_uri": "u",
            "folder_name": "F",
            "name": "N",
        },
        "result": None,
    }
    conn = MagicMock()
    with (
        patch(
            "app.api.v1.admin_remote_backups_oauth_gdrive.repo.get_active_by_state",
            AsyncMock(return_value=pending_row),
        ),
        patch(
            "app.api.v1.admin_remote_backups_oauth_gdrive.svc.finalize_session",
            AsyncMock(return_value=None),
        ),
    ):
        async with _client(_make_pool(conn)) as c:
            r = await c.get("/v1/admin/backup-remotes/oauth/gdrive/callback?code=AUTH&state=HAPPY")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "HAPPY" in r.text
    assert "postMessage" in r.text
    assert "true" in r.text  # ok: true in JSON literal


@pytest.mark.asyncio
async def test_oauth_callback_state_unknown_returns_error_html() -> None:
    """state inconnu/expiré → HTML d'erreur SANS postMessage."""
    from unittest.mock import AsyncMock, patch

    conn = MagicMock()
    with patch(
        "app.api.v1.admin_remote_backups_oauth_gdrive.repo.get_active_by_state",
        AsyncMock(return_value=None),
    ):
        async with _client(_make_pool(conn)) as c:
            r = await c.get("/v1/admin/backup-remotes/oauth/gdrive/callback?code=X&state=NOPE")

    assert r.status_code == 400
    assert "text/html" in r.headers["content-type"]
    # PAS de postMessage si state inconnu (opener pourrait être malveillant)
    assert "postMessage" not in r.text


@pytest.mark.asyncio
async def test_oauth_callback_user_refused() -> None:
    """error=access_denied → mark_failed + postMessage ok=false."""
    from unittest.mock import AsyncMock, patch

    pending_row = {
        "state": "REFUSED",
        "status": "pending",
        "payload": {
            "client_id": "c",
            "client_secret": "s",
            "redirect_uri": "u",
            "folder_name": "F",
            "name": "N",
        },
        "result": None,
    }
    conn = MagicMock()
    with (
        patch(
            "app.api.v1.admin_remote_backups_oauth_gdrive.repo.get_active_by_state",
            AsyncMock(return_value=pending_row),
        ),
        patch(
            "app.api.v1.admin_remote_backups_oauth_gdrive.svc.mark_session_failed",
            AsyncMock(return_value=None),
        ),
    ):
        async with _client(_make_pool(conn)) as c:
            r = await c.get(
                "/v1/admin/backup-remotes/oauth/gdrive/callback?state=REFUSED&error=access_denied"
            )

    assert r.status_code == 200
    assert "REFUSED" in r.text
    assert "false" in r.text  # ok: false in JSON literal


# ─── Tests GET /session/{state} ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_lookup_hides_secrets(admin_jwt_headers: dict[str, str]) -> None:
    """GET /session/{state} ne fuite JAMAIS de secret."""
    from unittest.mock import AsyncMock, patch

    row = {
        "state": "LOOKUP",
        "status": "authorized",
        "payload": {"client_id": "x", "client_secret": "SUPER-SECRET"},
        "result": {
            "refresh_token": "RT-SECRET",
            "user_email": "ok@x.y",
            "token_uri": "https://...",
        },
    }
    conn = MagicMock()
    with patch(
        "app.api.v1.admin_remote_backups_oauth_gdrive.repo.get_by_state",
        AsyncMock(return_value=row),
    ):
        async with _client(_make_pool(conn)) as c:
            r = await c.get(
                "/v1/admin/backup-remotes/oauth/gdrive/session/LOOKUP",
                headers=admin_jwt_headers,
            )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "authorized"
    assert body["result"]["user_email"] == "ok@x.y"
    raw = r.text
    assert "RT-SECRET" not in raw
    assert "SUPER-SECRET" not in raw
    assert "client_secret" not in raw
    assert "refresh_token" not in raw
    assert "token_uri" not in raw


@pytest.mark.asyncio
async def test_session_unknown_returns_unknown(admin_jwt_headers: dict[str, str]) -> None:
    """GET /session/{state} pour un state inexistant → {status: unknown}."""
    conn = MagicMock()
    with patch(
        "app.api.v1.admin_remote_backups_oauth_gdrive.repo.get_by_state",
        AsyncMock(return_value=None),
    ):
        async with _client(_make_pool(conn)) as c:
            r = await c.get(
                "/v1/admin/backup-remotes/oauth/gdrive/session/DOES_NOT_EXIST",
                headers=admin_jwt_headers,
            )

    assert r.status_code == 200
    assert r.json()["status"] == "unknown"


# ── /{id}/reauthorize ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reauthorize_creates_pending_with_target(
    admin_jwt_headers: dict[str, str],
) -> None:
    """Pour une connexion gdrive existante, crée une pending_session avec target_connection_id."""
    from uuid import uuid4

    conn_id = uuid4()
    fake_conn = MagicMock(
        id=conn_id,
        name="DriveX",
        kind="gdrive",
        config={
            "client_id": "cid",
            "folder_name": "F",
            "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
            "user_email": "old@x.y",
        },
    )
    fake_creds = {
        "client_secret": "csec-stored",
        "refresh_token": "rt-old",
        "scope": "https://www.googleapis.com/auth/drive.file",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    with (
        patch(
            "app.api.v1.admin_remote_backups.svc.get_connection",
            AsyncMock(return_value=fake_conn),
        ),
        patch(
            "app.api.v1.admin_remote_backups.svc.get_decrypted_credentials",
            AsyncMock(return_value=fake_creds),
        ),
        patch(
            "app.api.v1.admin_remote_backups.gdrive_svc.create_pending_session",
            AsyncMock(
                return_value={"auth_url": "https://accounts.google/...", "state": "REAUTH-STATE"}
            ),
        ),
        patch(
            "app.api.v1.admin_remote_backups.audit_log_insert",
            AsyncMock(),
        ),
    ):
        async with _client(_make_pool(MagicMock())) as c:
            r = await c.post(
                f"/v1/admin/backup-remotes/{conn_id}/reauthorize",
                headers=admin_jwt_headers,
            )
    assert r.status_code == 200
    assert r.json()["state"] == "REAUTH-STATE"


@pytest.mark.asyncio
async def test_reauthorize_404_when_connection_missing(
    admin_jwt_headers: dict[str, str],
) -> None:
    from uuid import uuid4

    with patch(
        "app.api.v1.admin_remote_backups.svc.get_connection",
        AsyncMock(return_value=None),
    ):
        async with _client(_make_pool(MagicMock())) as c:
            r = await c.post(
                f"/v1/admin/backup-remotes/{uuid4()}/reauthorize",
                headers=admin_jwt_headers,
            )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reauthorize_400_when_not_gdrive(
    admin_jwt_headers: dict[str, str],
) -> None:
    from uuid import uuid4

    conn_id = uuid4()
    fake_conn = MagicMock(id=conn_id, name="SftpX", kind="sftp", config={})
    with patch(
        "app.api.v1.admin_remote_backups.svc.get_connection",
        AsyncMock(return_value=fake_conn),
    ):
        async with _client(_make_pool(MagicMock())) as c:
            r = await c.post(
                f"/v1/admin/backup-remotes/{conn_id}/reauthorize",
                headers=admin_jwt_headers,
            )
    assert r.status_code == 400
