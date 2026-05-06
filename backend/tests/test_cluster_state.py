"""Tests ClusterState (LOT_21A)."""
from __future__ import annotations

import base64
import datetime

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_is_epoch_coherent_returns_true_when_ram_geq_db() -> None:
    from app.core.cluster_state import ClusterState
    state = ClusterState(session_epoch=10)
    assert state.is_epoch_coherent(10) is True
    assert state.is_epoch_coherent(5) is True


def test_is_epoch_coherent_returns_false_when_ram_lt_db() -> None:
    from app.core.cluster_state import ClusterState
    state = ClusterState(session_epoch=5)
    assert state.is_epoch_coherent(10) is False


def test_update_from_db_detects_epoch_change() -> None:
    from app.core.cluster_state import ClusterState
    state = ClusterState(session_epoch=1)
    changes = state.update_from_db(
        epoch=2,
        maintenance_active=False,
        maintenance_reason=None,
        maintenance_started_at=None,
        maintenance_effective_at=None,
        maintenance_estimated_end_at=None,
    )
    assert "epoch" in changes
    assert state.session_epoch == 2


def test_update_from_db_detects_maintenance_toggle() -> None:
    from app.core.cluster_state import ClusterState
    state = ClusterState(maintenance_active=False)
    changes = state.update_from_db(
        epoch=0,
        maintenance_active=True,
        maintenance_reason="db migration",
        maintenance_started_at=datetime.datetime(2026, 5, 5, tzinfo=datetime.UTC),
        maintenance_effective_at=None,
        maintenance_estimated_end_at=None,
    )
    assert "maintenance" in changes
    assert state.maintenance_active is True
    assert state.maintenance_reason == "db migration"


def test_update_from_db_returns_empty_changes_when_idempotent() -> None:
    from app.core.cluster_state import ClusterState
    state = ClusterState(session_epoch=5, maintenance_active=False)
    changes = state.update_from_db(
        epoch=5,
        maintenance_active=False,
        maintenance_reason=None,
        maintenance_started_at=None,
        maintenance_effective_at=None,
        maintenance_estimated_end_at=None,
    )
    assert changes == []


def test_update_from_db_sets_last_synced_at() -> None:
    from app.core.cluster_state import ClusterState
    state = ClusterState()
    before = datetime.datetime.now(datetime.UTC)
    state.update_from_db(
        epoch=1,
        maintenance_active=False,
        maintenance_reason=None,
        maintenance_started_at=None,
        maintenance_effective_at=None,
        maintenance_estimated_end_at=None,
    )
    assert state.last_synced_at is not None
    assert state.last_synced_at >= before
