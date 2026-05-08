"""Tests bootstrap idempotent du local-admin user (LOT_56)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_EMAIL", "admin@harpocrate.local")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_DISPLAY_NAME", "Local Admin")


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


@pytest.mark.asyncio
async def test_inserts_when_absent() -> None:
    from app.services import local_admin_bootstrap

    new_id = uuid4()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)  # email absent
    conn.fetchval = AsyncMock(return_value=new_id)  # INSERT renvoie l'id
    pool = _make_pool(conn)

    await local_admin_bootstrap.ensure_local_admin_user(pool)

    assert conn.fetchval.await_count == 1
    sql_call = conn.fetchval.await_args_list[0]
    assert "INSERT INTO users" in sql_call.args[0]
    assert "is_system" in sql_call.args[0]


@pytest.mark.asyncio
async def test_idempotent_when_already_system_user() -> None:
    """Une row is_system=TRUE existante → pas de re-INSERT."""
    from app.services import local_admin_bootstrap

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": uuid4(), "is_system": True})
    conn.fetchval = AsyncMock()  # ne devrait pas être appelé
    pool = _make_pool(conn)

    await local_admin_bootstrap.ensure_local_admin_user(pool)

    assert conn.fetchval.await_count == 0


@pytest.mark.asyncio
async def test_raises_when_email_used_by_real_user() -> None:
    """Si un vrai user (is_system=FALSE) a déjà cet email, refus explicite."""
    from app.services import local_admin_bootstrap

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": uuid4(), "is_system": False})
    pool = _make_pool(conn)

    with pytest.raises(local_admin_bootstrap.LocalAdminEmailConflictError):
        await local_admin_bootstrap.ensure_local_admin_user(pool)
