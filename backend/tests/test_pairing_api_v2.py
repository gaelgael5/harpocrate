"""Tests endpoints REST pairing v2 (LOT 5 — échange d'URL signée)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


def _build_test_app() -> tuple:
    from fastapi import FastAPI

    from app.api.v1 import admin_replication_pairing

    app = FastAPI()
    app.include_router(admin_replication_pairing.router, prefix="/v1")
    from fastapi.testclient import TestClient

    return TestClient(app), admin_replication_pairing


def _make_pool_mock() -> MagicMock:
    fake_conn = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    fake_pool = MagicMock()
    fake_pool.acquire.return_value = ctx
    return fake_pool


def test_init_v2_requires_admin_auth() -> None:
    client, _ = _build_test_app()
    r = client.post(
        "/v1/admin/replication/pairing/init-v2",
        json={"standby_url": "https://b.example/"},
    )
    assert r.status_code == 401


def test_accept_v2_requires_admin_auth() -> None:
    client, _ = _build_test_app()
    r = client.post(
        "/v1/admin/replication/pairing/accept-v2",
        json={"pairing_url": "https://a.example/pair?sid=" + str(uuid4()) + "&t=" + "a" * 32},
    )
    assert r.status_code == 401


def test_confirm_v2_does_not_require_auth() -> None:
    """/confirm-v2 est appelé inter-instances — pas de JWT exigé."""
    client, mod = _build_test_app()

    async def fake_confirm(conn, **kw):
        return {
            "master_host": "10.0.0.1",
            "master_port": 5432,
            "replication_user": "rep_x",
            "replication_password": "pwd_x",
            "application_name": "app_x",
            "node_id": "11111111-1111-1111-1111-111111111111",
        }

    with (
        patch.object(mod.svc_v2, "confirm_master_v2", side_effect=fake_confirm),
        patch(
            "app.api.v1.admin_replication_pairing.get_pool",
            AsyncMock(return_value=_make_pool_mock()),
        ),
    ):
        r = client.post(
            "/v1/admin/replication/pairing/confirm-v2",
            json={
                "session_id": str(uuid4()),
                "token": "a" * 32,
                "standby_url": "https://b.example/",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["master_host"] == "10.0.0.1"


def test_confirm_v2_invalid_token_returns_403() -> None:
    client, mod = _build_test_app()

    async def fake_confirm(conn, **kw):
        raise mod.svc.InvalidCodeError("token_mismatch")

    with (
        patch.object(mod.svc_v2, "confirm_master_v2", side_effect=fake_confirm),
        patch(
            "app.api.v1.admin_replication_pairing.get_pool",
            AsyncMock(return_value=_make_pool_mock()),
        ),
    ):
        r = client.post(
            "/v1/admin/replication/pairing/confirm-v2",
            json={
                "session_id": str(uuid4()),
                "token": "b" * 32,
                "standby_url": "https://b.example/",
            },
        )
    assert r.status_code == 403


def test_confirm_v2_too_many_attempts_returns_429() -> None:
    client, mod = _build_test_app()

    async def fake_confirm(conn, **kw):
        raise mod.svc.TooManyAttemptsError("too_many_attempts")

    with (
        patch.object(mod.svc_v2, "confirm_master_v2", side_effect=fake_confirm),
        patch(
            "app.api.v1.admin_replication_pairing.get_pool",
            AsyncMock(return_value=_make_pool_mock()),
        ),
    ):
        r = client.post(
            "/v1/admin/replication/pairing/confirm-v2",
            json={
                "session_id": str(uuid4()),
                "token": "a" * 32,
                "standby_url": "https://b.example/",
            },
        )
    assert r.status_code == 429


def test_confirm_v2_rejects_short_token_via_pydantic() -> None:
    """Validator du DTO : token doit être 32 hex chars."""
    client, _ = _build_test_app()
    r = client.post(
        "/v1/admin/replication/pairing/confirm-v2",
        json={
            "session_id": str(uuid4()),
            "token": "short",
            "standby_url": "https://b/",
        },
    )
    assert r.status_code == 422
