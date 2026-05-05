"""Tests ClusterSync — refresh DB et handler NOTIFY (LOT_21A)."""
from __future__ import annotations

import base64
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _pool_with_rows(epoch: int, maintenance: dict[str, Any] | None) -> MagicMock:
    """Build un fake pool dont fetchrow renvoie séquentiellement epoch row puis maint row."""
    epoch_row = {"epoch": epoch} if epoch is not None else None
    maint_row = {"value": maintenance} if maintenance is not None else None

    fake_conn = AsyncMock()
    fake_conn.fetchrow = AsyncMock(side_effect=[epoch_row, maint_row])

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return fake_conn

        async def __aexit__(self, *_a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


@pytest.mark.asyncio
async def test_refresh_from_db_updates_cluster_state() -> None:
    """Le refresh lit DB et applique sur cluster_state."""
    from app.core.cluster_state import cluster_state
    from app.core.cluster_sync import ClusterSync

    cluster_state.session_epoch = 0
    cluster_state.maintenance_active = False

    pool = _pool_with_rows(
        epoch=7,
        maintenance={
            "active": True,
            "reason": "scheduled",
            "started_at": "2026-05-05T20:00:00+00:00",
        },
    )
    sync = ClusterSync(pool)
    await sync._refresh_from_db()

    assert cluster_state.session_epoch == 7
    assert cluster_state.maintenance_active is True
    assert cluster_state.maintenance_reason == "scheduled"
    assert cluster_state.last_synced_at is not None


@pytest.mark.asyncio
async def test_refresh_from_db_handles_missing_maintenance_row() -> None:
    """Si la ligne maintenance_mode est absente, on désactive proprement."""
    from app.core.cluster_state import cluster_state
    from app.core.cluster_sync import ClusterSync

    cluster_state.session_epoch = 0
    cluster_state.maintenance_active = True

    pool = _pool_with_rows(epoch=3, maintenance=None)
    sync = ClusterSync(pool)
    await sync._refresh_from_db()

    assert cluster_state.session_epoch == 3
    assert cluster_state.maintenance_active is False


@pytest.mark.asyncio
async def test_handle_notify_epoch_triggers_refresh() -> None:
    """Réception d'un NOTIFY epoch_changed → refresh DB."""
    from app.core.cluster_sync import CHANNEL_EPOCH, ClusterSync

    pool = _pool_with_rows(epoch=99, maintenance={"active": False})
    sync = ClusterSync(pool)
    sync._refresh_from_db = AsyncMock()  # type: ignore[method-assign]

    await sync._handle_notify(CHANNEL_EPOCH, {"new_value": 99})
    sync._refresh_from_db.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_notify_maintenance_triggers_refresh() -> None:
    from app.core.cluster_sync import CHANNEL_MAINTENANCE, ClusterSync

    pool = _pool_with_rows(epoch=1, maintenance={"active": True})
    sync = ClusterSync(pool)
    sync._refresh_from_db = AsyncMock()  # type: ignore[method-assign]

    await sync._handle_notify(CHANNEL_MAINTENANCE, {})
    sync._refresh_from_db.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_notify_jwks_does_not_refresh_state() -> None:
    """JWKS invalidation ne déclenche PAS un refresh de l'état partagé."""
    from app.core.cluster_sync import CHANNEL_JWKS, ClusterSync

    pool = _pool_with_rows(epoch=1, maintenance={"active": False})
    sync = ClusterSync(pool)
    sync._refresh_from_db = AsyncMock()  # type: ignore[method-assign]

    await sync._handle_notify(CHANNEL_JWKS, {})
    sync._refresh_from_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_parses_str_iso_dates_in_maintenance_payload() -> None:
    """Les dates ISO en string sont correctement parsées en datetime."""
    from app.core.cluster_state import cluster_state
    from app.core.cluster_sync import ClusterSync

    pool = _pool_with_rows(
        epoch=1,
        maintenance={
            "active": True,
            "estimated_end_at": "2026-12-31T23:59:00+00:00",
        },
    )
    sync = ClusterSync(pool)
    await sync._refresh_from_db()

    assert cluster_state.maintenance_estimated_end_at == datetime.datetime(
        2026, 12, 31, 23, 59, 0, tzinfo=datetime.UTC
    )
