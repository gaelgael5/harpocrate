"""Tests des helpers pg_notify cluster (LOT_21A)."""
from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")
    monkeypatch.setenv("HARPOCRATE_INSTANCE_ID", "test-instance-99")
    # Pas de réassignation de settings (cf. test_admin_remote_backups.py:env).
    import app.core.config

    _new_s = app.core.config.Settings()
    for _a, _v in _new_s.model_dump().items():
        monkeypatch.setattr(app.core.config.settings, _a, _v)


@pytest.mark.asyncio
async def test_notify_epoch_changed_emits_correct_payload() -> None:
    from app.services import cluster_notify

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)

    await cluster_notify.notify_epoch_changed(conn, 42)

    assert conn.execute.await_count == 1
    args, _ = conn.execute.await_args
    assert "pg_notify('harpocrate_epoch_changed'" in args[0]
    payload = json.loads(args[1])
    assert payload["event"] == "epoch_changed"
    assert payload["new_value"] == 42
    assert payload["emitted_by"] == "test-instance-99"


@pytest.mark.asyncio
async def test_notify_maintenance_changed_includes_active_flag() -> None:
    from app.services import cluster_notify

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)

    await cluster_notify.notify_maintenance_changed(conn, active=True)

    args, _ = conn.execute.await_args
    assert "pg_notify('harpocrate_maintenance_changed'" in args[0]
    payload = json.loads(args[1])
    assert payload["event"] == "maintenance_changed"
    assert payload["active"] is True


@pytest.mark.asyncio
async def test_notify_jwks_invalidated_emits_event() -> None:
    from app.services import cluster_notify

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)

    await cluster_notify.notify_jwks_invalidated(conn)

    args, _ = conn.execute.await_args
    assert "pg_notify('harpocrate_jwks_invalidated'" in args[0]
    payload = json.loads(args[1])
    assert payload["event"] == "jwks_invalidated"
