"""Tests unitaires P1.5 — require_any_auth_no_scope (auth sans wallet ni permission)."""

from __future__ import annotations

import base64
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


class _FakeConn:
    pass


class _FakeCtx:
    async def __aenter__(self) -> _FakeConn:
        return _FakeConn()

    async def __aexit__(self, *a: Any) -> None:
        pass


class _FakePool:
    def acquire(self) -> _FakeCtx:
        return _FakeCtx()


@pytest.fixture(autouse=True)
def fake_pool() -> Generator[None, None, None]:
    """Injecte un pool factice pour que get_pool() ne lève pas RuntimeError."""
    from app.db import pool as pool_mod

    original = pool_mod._pool
    pool_mod._pool = _FakePool()  # type: ignore[assignment]
    yield
    pool_mod._pool = original


def _build_test_app() -> FastAPI:
    """Mini-app avec une route protégée par require_any_auth_no_scope."""
    from fastapi import Depends

    from app.core.api_key_auth import require_any_auth_no_scope

    app = FastAPI()

    @app.get("/test-protected")
    async def protected(_auth: Any = Depends(require_any_auth_no_scope)) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_no_scope_no_token_returns_401() -> None:
    app = _build_test_app()
    client = TestClient(app)
    r = client.get("/test-protected")
    assert r.status_code == 401


def test_no_scope_with_invalid_token_returns_401() -> None:
    app = _build_test_app()
    client = TestClient(app)
    r = client.get("/test-protected", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_no_scope_with_valid_jwt_returns_200() -> None:
    # JWT path: only validates signature, no DB lookup — pool fixture not needed for JWT.
    app = _build_test_app()
    client = TestClient(app)
    r = client.get(
        "/test-protected",
        headers={"Authorization": f"Bearer {make_jwt_token()}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": "yes"}
