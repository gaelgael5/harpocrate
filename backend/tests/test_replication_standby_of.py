"""Tests endpoint GET /v1/admin/replication/standby-of (LOT 5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _build_test_app() -> tuple:
    """Construit une mini-app avec uniquement le router admin_replication.

    Retourne (TestClient, app FastAPI, module admin_replication).
    `dependency_overrides` doit être posé sur `app`, pas sur `router`.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import admin_replication

    app = FastAPI()
    app.include_router(admin_replication.router, prefix="/v1")
    return TestClient(app), app, admin_replication


def _make_pool_mock() -> MagicMock:
    """Pool factice compatible avec `async with pool.acquire() as conn`."""
    fake_conn = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    fake_pool = MagicMock()
    fake_pool.acquire.return_value = ctx
    return fake_pool


def test_standby_of_requires_admin_auth() -> None:
    """Sans Bearer JWT, GET /standby-of renvoie 401."""
    client, _app, _ = _build_test_app()
    r = client.get("/v1/admin/replication/standby-of")
    assert r.status_code == 401


def test_standby_of_returns_null_when_not_asservi() -> None:
    """Quand la clé system_metadata vaut None, l'endpoint retourne {is_standby_of: null}."""
    client, app, mod = _build_test_app()

    async def fake_get_value(conn, key):
        return None

    from app.core import admin_auth

    async def fake_admin():
        return admin_auth.AdminUser(
            user_id="00000000-0000-0000-0000-000000000000",  # type: ignore[arg-type]
            keycloak_sub="test",
            email="test@example.com",
            display_name="Test",
        )

    app.dependency_overrides[admin_auth.require_admin_jwt] = fake_admin
    try:
        with (
            patch.object(mod.meta_repo, "get_value", side_effect=fake_get_value),
            patch(
                "app.api.v1.admin_replication.get_pool",
                AsyncMock(return_value=_make_pool_mock()),
            ),
        ):
            r = client.get(
                "/v1/admin/replication/standby-of",
                headers={"Authorization": "Bearer fake"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"is_standby_of": None}


def test_standby_of_returns_master_url_when_asservi() -> None:
    """Quand la clé system_metadata contient une URL, l'endpoint la retourne."""
    client, app, mod = _build_test_app()

    master_url = "https://master.example.com"

    async def fake_get_value(conn, key):
        return master_url

    from app.core import admin_auth

    async def fake_admin():
        return admin_auth.AdminUser(
            user_id="00000000-0000-0000-0000-000000000000",  # type: ignore[arg-type]
            keycloak_sub="test",
            email="test@example.com",
            display_name="Test",
        )

    app.dependency_overrides[admin_auth.require_admin_jwt] = fake_admin
    try:
        with (
            patch.object(mod.meta_repo, "get_value", side_effect=fake_get_value),
            patch(
                "app.api.v1.admin_replication.get_pool",
                AsyncMock(return_value=_make_pool_mock()),
            ),
        ):
            r = client.get(
                "/v1/admin/replication/standby-of",
                headers={"Authorization": "Bearer fake"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"is_standby_of": master_url}
