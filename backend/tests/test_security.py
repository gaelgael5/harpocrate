"""Tests unitaires — validation JWT (app.core.security)."""
from __future__ import annotations

import base64
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")
    # Patch le settings référencé par security.py (via son import direct).
    # On importe explicitement pour s'assurer que le module est dans sys.modules,
    # puis on accède au settings lié au moment de l'import du module (qui peut être
    # différent de app.core.config.settings si ce dernier a été rechargé).
    import app.core.security

    _sec_settings = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec_settings, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec_settings, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec_settings, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture()
def patch_jwks() -> Generator[dict[str, Any], None, None]:
    """Injecte les clés de test dans le cache JWKS."""
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield jwks_cache._keys
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _detail(exc: Any) -> dict[str, Any]:
    """Extrait le detail d'une HTTPException en tant que dict."""
    return exc.value.detail  # type: ignore[no-any-return]


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jwt_validation_ok(patch_jwks: dict[str, Any]) -> None:
    """Un token valide retourne un CurrentUser correctement peuplé."""
    from app.core.security import require_jwt_user

    token = make_jwt_token()
    result = await require_jwt_user(authorization=f"Bearer {token}")
    assert result.keycloak_sub == "test-sub-001"
    assert result.email == "alice@example.com"
    assert result.display_name == "Alice Test"


@pytest.mark.asyncio
async def test_jwt_expired(patch_jwks: dict[str, Any]) -> None:
    """Un token expiré lève HTTPException 401."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    token = make_jwt_token(exp_offset=-10)
    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401
    assert _detail(exc_info)["error"] == "token_expired"


@pytest.mark.asyncio
async def test_jwt_invalid_audience(patch_jwks: dict[str, Any]) -> None:
    """Un token avec une mauvaise audience lève HTTPException 401."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    token = make_jwt_token(audience="wrong-client")
    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401
    assert _detail(exc_info)["error"] == "invalid_audience"


@pytest.mark.asyncio
async def test_jwt_unknown_kid_triggers_refresh() -> None:
    """Un kid inconnu déclenche un appel à _fetch_jwks."""
    from fastapi import HTTPException

    from app.core import jwks_cache
    from app.core.security import require_jwt_user

    # On vide le cache
    jwks_cache._keys.clear()

    token = make_jwt_token()
    mock_fetch = AsyncMock(side_effect=lambda: None)  # fetch ne peuple pas le cache

    with patch("app.core.jwks_cache._fetch_jwks", mock_fetch), pytest.raises(
        HTTPException
    ) as exc_info:
        await require_jwt_user(authorization=f"Bearer {token}")

    mock_fetch.assert_awaited_once()
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_api_key_token_rejected(patch_jwks: dict[str, Any]) -> None:
    """Un token commençant par 'hrpv_' est rejeté avec api_key_not_allowed_here."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization="Bearer hrpv_some_api_key_value")
    assert exc_info.value.status_code == 401
    assert _detail(exc_info)["error"] == "api_key_not_allowed_here"


@pytest.mark.asyncio
async def test_jwt_missing_bearer() -> None:
    """Absence de header Authorization lève HTTPException 401."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization=None)
    assert exc_info.value.status_code == 401
    assert _detail(exc_info)["error"] == "missing_bearer_token"


@pytest.mark.asyncio
async def test_jwt_missing_bearer_wrong_scheme() -> None:
    """Header Authorization sans 'Bearer' lève 401."""
    from fastapi import HTTPException

    from app.core.security import require_jwt_user

    with pytest.raises(HTTPException) as exc_info:
        await require_jwt_user(authorization="Basic dXNlcjpwYXNz")
    assert exc_info.value.status_code == 401
    assert _detail(exc_info)["error"] == "missing_bearer_token"
