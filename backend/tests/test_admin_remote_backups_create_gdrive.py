"""Création d'une connexion gdrive via POST /admin/backup-remotes (consomme oauth_state)."""

from __future__ import annotations

import base64
import datetime
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

# ─── Helpers ─────────────────────────────────────────────────────────────────


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


# ─── Tests POST /admin/backup-remotes (kind=gdrive) ──────────────────────────


@pytest.mark.asyncio
async def test_create_gdrive_consumes_authorized_session(
    admin_jwt_headers: dict[str, str],
) -> None:
    """Flow nominal : pending session authorized → INSERT + DELETE pending."""
    pending = {
        "state": "OK-CREATE",
        "status": "authorized",
        "payload": {
            "name": "Drive perso",
            "client_id": "cid",
            "client_secret": "csec",
            "folder_name": "Backups",
            "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
        },
        "result": {
            "refresh_token": "RT",
            "user_email": "ok@x.y",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        "target_connection_id": None,
    }
    new_id = uuid4()
    with (
        patch(
            "app.api.v1.admin_remote_backups.oauth_repo.get_by_state",
            AsyncMock(return_value=pending),
        ),
        patch(
            "app.api.v1.admin_remote_backups.svc.create_connection",
            AsyncMock(return_value=new_id),
        ),
        patch(
            "app.api.v1.admin_remote_backups.oauth_repo.delete_by_state",
            AsyncMock(return_value=1),
        ),
    ):
        async with _client(_make_pool(MagicMock())) as c:
            r = await c.post(
                "/v1/admin/backup-remotes",
                json={
                    "name": "Drive perso",
                    "kind": "gdrive",
                    "config": {},
                    "credentials": {},
                    "oauth_state": "OK-CREATE",
                },
                headers=admin_jwt_headers,
            )
    assert r.status_code == 201
    assert r.json()["id"] == str(new_id)


@pytest.mark.asyncio
async def test_create_gdrive_missing_oauth_state_422(
    admin_jwt_headers: dict[str, str],
) -> None:
    """oauth_state absent avec kind=gdrive → 422."""
    async with _client(_make_pool(MagicMock())) as c:
        r = await c.post(
            "/v1/admin/backup-remotes",
            json={"name": "X", "kind": "gdrive", "config": {}, "credentials": {}},
            headers=admin_jwt_headers,
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_gdrive_pending_session_not_authorized_422(
    admin_jwt_headers: dict[str, str],
) -> None:
    """Session encore en status 'pending' → 422."""
    pending = {
        "state": "STILL-PENDING",
        "status": "pending",
        "payload": {
            "name": "X",
            "client_id": "c",
            "client_secret": "s",
            "folder_name": "F",
            "redirect_uri": "u",
        },
        "result": None,
        "target_connection_id": None,
    }
    with patch(
        "app.api.v1.admin_remote_backups.oauth_repo.get_by_state",
        AsyncMock(return_value=pending),
    ):
        async with _client(_make_pool(MagicMock())) as c:
            r = await c.post(
                "/v1/admin/backup-remotes",
                json={
                    "name": "X",
                    "kind": "gdrive",
                    "config": {},
                    "credentials": {},
                    "oauth_state": "STILL-PENDING",
                },
                headers=admin_jwt_headers,
            )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_gdrive_reauthorize_updates_existing_connection(
    admin_jwt_headers: dict[str, str],
) -> None:
    """target_connection_id non-null → UPDATE + DELETE pending (cas re-autorisation)."""
    existing_id = uuid4()
    pending = {
        "state": "REAUTH-OK",
        "status": "authorized",
        "payload": {
            "name": "Drive réautorisé",
            "client_id": "cid2",
            "client_secret": "csec2",
            "folder_name": "Backups2",
            "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
        },
        "result": {
            "refresh_token": "RT2",
            "user_email": "new@x.y",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        "target_connection_id": existing_id,
    }
    with (
        patch(
            "app.api.v1.admin_remote_backups.oauth_repo.get_by_state",
            AsyncMock(return_value=pending),
        ),
        patch(
            "app.api.v1.admin_remote_backups.svc.update_connection",
            AsyncMock(return_value=1),
        ),
        patch(
            "app.api.v1.admin_remote_backups.oauth_repo.delete_by_state",
            AsyncMock(return_value=1),
        ),
    ):
        async with _client(_make_pool(MagicMock())) as c:
            r = await c.post(
                "/v1/admin/backup-remotes",
                json={
                    "name": "Drive réautorisé",
                    "kind": "gdrive",
                    "config": {},
                    "credentials": {},
                    "oauth_state": "REAUTH-OK",
                },
                headers=admin_jwt_headers,
            )
    assert r.status_code == 201
    assert r.json()["id"] == str(existing_id)
