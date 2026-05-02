"""Tests pour l'authentification locale admin (POST /v1/auth/local-login).

Couvre :
- Désactivé → 404
- Mauvais username → 401
- Mauvais password → 401
- Happy path → JWT HS256 valide
- Token local accepté par require_jwt_user
- Token local avec mauvaise signature → rejeté
- Token local expiré → rejeté
- Token Keycloak (RS256) toujours accepté en parallèle
- GET /v1/config/auth-modes retourne le statut local
"""
from __future__ import annotations

import base64
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

# ─── Clé HMAC de test ─────────────────────────────────────────────────────────

_HMAC_KEY_BYTES = b"t" * 32
_HMAC_KEY_B64 = base64.b64encode(_HMAC_KEY_BYTES).decode()

_LOCAL_ISSUER = "harpocrate-local"

# ─── Fixtures d'environnement ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", _HMAC_KEY_B64)
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_ENABLED", "false")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_USERNAME", "admin")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_PASSWORD", "secret123")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_EMAIL", "admin@harpocrate.local")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_DISPLAY_NAME", "Local Admin")

    # Patch les settings dans les modules qui les ont importés
    import app.api.v1.auth_local
    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)
    monkeypatch.setattr(_sec, "hmac_key", _HMAC_KEY_B64)

    _auth_local_settings = app.api.v1.auth_local.__dict__["settings"]
    monkeypatch.setattr(_auth_local_settings, "keycloak_client_id", TEST_AUDIENCE)
    monkeypatch.setattr(_auth_local_settings, "hmac_key", _HMAC_KEY_B64)
    monkeypatch.setattr(_auth_local_settings, "admin_local_email", "admin@harpocrate.local")
    monkeypatch.setattr(_auth_local_settings, "admin_local_display_name", "Local Admin")


@pytest.fixture(autouse=True)
def patch_jwks() -> Any:
    """Injecte la clé de test dans le cache JWKS pour tous les tests."""
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_conn_mock() -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)

    class FakeTxCtx:
        async def __aenter__(self) -> FakeTxCtx:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

    conn.transaction = MagicMock(return_value=FakeTxCtx())
    return conn


def _make_pool_with_conn(conn: MagicMock) -> MagicMock:
    class FakeAcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: object) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=FakeAcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _make_local_jwt(
    sub: str = "local-admin",
    issuer: str = _LOCAL_ISSUER,
    audience: str = TEST_AUDIENCE,
    exp_offset: int = 3600,
    hmac_key: bytes = _HMAC_KEY_BYTES,
) -> str:
    """Génère un JWT HS256 simulant un token admin local."""
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": "admin@harpocrate.local",
        "name": "Local Admin",
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, hmac_key, algorithm="HS256")


# ─── Tests endpoint local-login ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_login_disabled_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quand admin_local_enabled=False → 404 not_found."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", False
    )

    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)
    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/auth/local-login",
            json={"username": "admin", "password": "secret123"},
        )
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_local_login_invalid_username_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mauvais username → 401 invalid_credentials."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", True
    )
    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_username", "admin"
    )
    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_password", "secret123"
    )

    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)
    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/auth/local-login",
            json={"username": "wrong_user", "password": "secret123"},
        )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_local_login_invalid_password_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mauvais password → 401 invalid_credentials."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", True
    )
    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_username", "admin"
    )
    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_password", "secret123"
    )

    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)
    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/auth/local-login",
            json={"username": "admin", "password": "wrong_pass"},
        )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_local_login_happy_path_returns_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Username+password corrects → 200 avec access_token HS256 valide."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", True
    )
    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_username", "admin"
    )
    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_password", "secret123"
    )

    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)
    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/auth/local-login",
            json={"username": "admin", "password": "secret123"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 86400
    token = body["access_token"]

    # Vérification du payload sans passer par la dependency FastAPI
    decoded = jwt.decode(
        token,
        _HMAC_KEY_BYTES,
        algorithms=["HS256"],
        audience=TEST_AUDIENCE,
        issuer=_LOCAL_ISSUER,
    )
    assert decoded["sub"] == "local-admin"
    assert decoded["email"] == "admin@harpocrate.local"
    assert decoded["iss"] == _LOCAL_ISSUER


# ─── Tests require_jwt_user avec token local ──────────────────────────────────


@pytest.mark.asyncio
async def test_local_token_accepted_by_require_jwt_user() -> None:
    """Un token HS256 local valide est accepté par require_jwt_user."""
    from app.core.security import require_jwt_user

    token = _make_local_jwt()
    result = await require_jwt_user(authorization=f"Bearer {token}")
    assert result.keycloak_sub == "local-admin"
    assert result.email == "admin@harpocrate.local"
    assert result.display_name == "Local Admin"


@pytest.mark.asyncio
async def test_local_token_with_wrong_signature_rejected() -> None:
    """Un token HS256 signé avec une autre clé est rejeté."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    wrong_key = b"w" * 32
    token = _make_local_jwt(hmac_key=wrong_key)
    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_local_token_expired_rejected() -> None:
    """Un token HS256 local expiré est rejeté avec token_expired."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    token = _make_local_jwt(exp_offset=-10)
    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401
    detail: dict[str, Any] = exc_info.value.detail  # type: ignore[assignment]
    assert detail["error"] == "token_expired"


@pytest.mark.asyncio
async def test_keycloak_token_still_works_alongside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le chemin Keycloak RS256 fonctionne toujours quand local auth est activé."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", True
    )

    from app.core.security import require_jwt_user

    token = make_jwt_token()
    result = await require_jwt_user(authorization=f"Bearer {token}")
    assert result.keycloak_sub == "test-sub-001"
    assert result.email == "alice@example.com"


# ─── Tests GET /v1/config/auth-modes ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_auth_modes_returns_local_status_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /v1/config/auth-modes retourne local_login=false quand désactivé."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", False
    )

    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)
    async with _make_client(pool) as client:
        r = await client.get("/v1/config/auth-modes")
    assert r.status_code == 200
    body = r.json()
    assert body["oidc"] is True
    assert body["local_login"] is False


@pytest.mark.asyncio
async def test_config_auth_modes_returns_local_status_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /v1/config/auth-modes retourne local_login=true quand activé."""
    import app.api.v1.auth_local

    monkeypatch.setattr(
        app.api.v1.auth_local.__dict__["settings"], "admin_local_enabled", True
    )

    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)
    async with _make_client(pool) as client:
        r = await client.get("/v1/config/auth-modes")
    assert r.status_code == 200
    body = r.json()
    assert body["oidc"] is True
    assert body["local_login"] is True
