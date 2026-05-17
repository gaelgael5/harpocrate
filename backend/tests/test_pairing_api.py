"""Tests endpoints REST pairing /v1/admin/replication/pairing/* (LOT 2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _build_test_app() -> tuple:
    """Construit une mini-app avec uniquement le router pairing pour les tests."""
    from fastapi import FastAPI

    from app.api.v1 import admin_replication_pairing

    app = FastAPI()
    app.include_router(admin_replication_pairing.router, prefix="/v1")
    from fastapi.testclient import TestClient

    return TestClient(app), admin_replication_pairing


def _make_pool_mock() -> MagicMock:
    """Retourne un mock de pool asyncpg compatible avec `async with pool.acquire() as conn`.

    L'endpoint fait :
        pool = await get_pool()        # get_pool est un AsyncMock → pool = MagicMock
        async with pool.acquire() as conn: ...   # acquire() doit être un async ctx mgr

    On patch `get_pool` avec `new_callable=AsyncMock` de sorte que `await get_pool()`
    retourne un `MagicMock` dont `.acquire()` supporte `async with`.
    """
    fake_conn = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    fake_pool = MagicMock()
    fake_pool.acquire.return_value = ctx
    return fake_pool


def test_init_requires_admin_auth() -> None:
    """Sans Bearer JWT, /init renvoie 401."""
    client, _ = _build_test_app()
    r = client.post(
        "/v1/admin/replication/pairing/init",
        json={"partner_url": "https://b/"},
    )
    assert r.status_code == 401


def test_confirm_does_not_require_auth() -> None:
    """/confirm est appelé inter-instances (B → A) — pas de JWT exigé."""
    client, mod = _build_test_app()

    async def fake_confirm(conn, **kw):
        return {
            "master_host": "10.0.0.1",
            "master_port": 5432,
            "replication_user": "rep_x",
            "replication_password": "pwd_x",
            "application_name": "app_x",
            "node_id": "11111111-1111-1111-1111-111111111111",
            "master_postgres_password": "master_pwd_x",
        }

    with (
        patch.object(mod.svc, "confirm_master", side_effect=fake_confirm),
        patch(
            "app.api.v1.admin_replication_pairing.get_pool",
            AsyncMock(return_value=_make_pool_mock()),
        ),
    ):
        r = client.post(
            "/v1/admin/replication/pairing/confirm",
            json={"code": "1234", "standby_url": "https://b/"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["master_host"] == "10.0.0.1"


def test_confirm_invalid_code_returns_403() -> None:
    client, mod = _build_test_app()

    async def fake_confirm(conn, **kw):
        raise mod.svc.InvalidCodeError("invalid_or_expired_code")

    with (
        patch.object(mod.svc, "confirm_master", side_effect=fake_confirm),
        patch(
            "app.api.v1.admin_replication_pairing.get_pool",
            AsyncMock(return_value=_make_pool_mock()),
        ),
    ):
        r = client.post(
            "/v1/admin/replication/pairing/confirm",
            json={"code": "0000", "standby_url": "https://b/"},
        )
    assert r.status_code == 403


def test_confirm_too_many_attempts_returns_429() -> None:
    client, mod = _build_test_app()

    async def fake_confirm(conn, **kw):
        raise mod.svc.TooManyAttemptsError("too_many_attempts")

    with (
        patch.object(mod.svc, "confirm_master", side_effect=fake_confirm),
        patch(
            "app.api.v1.admin_replication_pairing.get_pool",
            AsyncMock(return_value=_make_pool_mock()),
        ),
    ):
        r = client.post(
            "/v1/admin/replication/pairing/confirm",
            json={"code": "1234", "standby_url": "https://b/"},
        )
    assert r.status_code == 429


def test_accept_requires_admin_auth() -> None:
    """Sans Bearer JWT, /accept renvoie 401."""
    client, _ = _build_test_app()
    r = client.post(
        "/v1/admin/replication/pairing/accept",
        json={"master_url": "https://a/", "code": "1234"},
    )
    assert r.status_code == 401


def test_status_requires_admin_auth() -> None:
    client, _ = _build_test_app()
    r = client.get(
        "/v1/admin/replication/pairing/11111111-1111-1111-1111-111111111111/status",
    )
    assert r.status_code == 401
