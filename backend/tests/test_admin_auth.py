"""Tests de la dependency require_admin_jwt — LOT_12A."""
from __future__ import annotations

import base64
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

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


def _admin_token() -> str:
    return make_jwt_token(extra_claims={"realm_access": {"roles": ["harpocrate-admin"]}})


def _user_token() -> str:
    return make_jwt_token()


def test_require_admin_jwt_accepts_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    from app.core.admin_auth import require_admin_jwt
    from app.services import admin_user_resolver

    # Court-circuite la résolution DB de l'user_id (pas de pool dans ce test).
    # Override l'autouse fixture du conftest pour vérifier qu'un UUID
    # spécifique est bien propagé jusqu'à AdminUser.
    fake_id = uuid4()

    async def _fake_resolve(*, keycloak_sub: str, email: str, display_name: str | None):
        return fake_id

    monkeypatch.setattr(admin_user_resolver, "resolve_admin_user_id", _fake_resolve)

    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True, "user_id": str(user.user_id)}

    client = TestClient(app_test)
    r = client.get("/admin-only", headers={"Authorization": f"Bearer {_admin_token()}"})
    assert r.status_code == 200
    assert r.json()["user_id"] == str(fake_id)


def test_require_admin_jwt_rejects_non_admin() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only", headers={"Authorization": f"Bearer {_user_token()}"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "admin_role_required"


def test_require_admin_jwt_rejects_api_key() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only", headers={"Authorization": "Bearer hrpv_sometoken"})
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "admin_jwt_only"


def test_require_admin_jwt_rejects_missing_auth() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only")
    assert r.status_code == 401
