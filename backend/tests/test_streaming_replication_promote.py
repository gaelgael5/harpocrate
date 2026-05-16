"""Tests promote_standby_to_master + get_promote_eligibility (failover MVP).

Le service gère la promotion d'un standby en master via `pg_promote()` côté
Postgres + nettoyage de `replication.is_standby_of` dans system_metadata.
Pré-condition : l'instance DOIT être en mode recovery (pg_is_in_recovery=t).
"""

from __future__ import annotations

import base64
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
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://standby.example/")


def _build_conn(fetchval_returns: list[Any]) -> MagicMock:
    """Construit un fake conn dont `fetchval` répond séquentiellement."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=fetchval_returns)
    conn.execute = AsyncMock(return_value=None)
    return conn


@pytest.mark.asyncio
async def test_get_promote_eligibility_returns_can_true_when_standby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si pg_is_in_recovery=true et is_standby_of est set, can_promote=True."""
    from app.services.streaming_replication import get_promote_eligibility

    conn = _build_conn(fetchval_returns=[True])
    monkeypatch.setattr(
        "app.db.repositories.system_metadata.get_value",
        AsyncMock(return_value="https://master.example/"),
    )

    result = await get_promote_eligibility(conn)
    assert result.can_promote is True
    assert result.current_role == "standby"
    assert result.master_url == "https://master.example/"
    assert result.reason_if_not is None


@pytest.mark.asyncio
async def test_get_promote_eligibility_returns_false_when_already_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si pg_is_in_recovery=false et is_standby_of est set → role=master, can=False."""
    from app.services.streaming_replication import get_promote_eligibility

    conn = _build_conn(fetchval_returns=[False])
    monkeypatch.setattr(
        "app.db.repositories.system_metadata.get_value",
        AsyncMock(return_value="https://old-master.example/"),
    )

    result = await get_promote_eligibility(conn)
    assert result.can_promote is False
    assert result.current_role == "master"
    assert result.reason_if_not == "already_master"


@pytest.mark.asyncio
async def test_get_promote_eligibility_returns_standalone_when_no_replication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si pg_is_in_recovery=false ET is_standby_of=None → role=standalone."""
    from app.services.streaming_replication import get_promote_eligibility

    conn = _build_conn(fetchval_returns=[False])
    monkeypatch.setattr(
        "app.db.repositories.system_metadata.get_value",
        AsyncMock(return_value=None),
    )

    result = await get_promote_eligibility(conn)
    assert result.can_promote is False
    assert result.current_role == "standalone"
    assert result.reason_if_not == "no_replication_configured"


@pytest.mark.asyncio
async def test_promote_standby_to_master_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cas nominal : in_recovery → pg_promote → not in_recovery → cleanup metadata."""
    from app.services.streaming_replication import promote_standby_to_master

    # 3 fetchval calls : in_recovery_before=True, pg_promote=True, in_recovery_after=False
    conn = _build_conn(fetchval_returns=[True, True, False])
    monkeypatch.setattr(
        "app.db.repositories.system_metadata.get_value",
        AsyncMock(return_value="https://old-master/"),
    )
    set_value_mock = AsyncMock()
    monkeypatch.setattr(
        "app.db.repositories.system_metadata.set_value", set_value_mock
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr("app.services.audit.audit_log_insert", audit_mock)

    result = await promote_standby_to_master(conn, actor_user_id=None)
    assert result.promoted is True
    assert result.old_master_url == "https://old-master/"

    # pg_promote a été appelé
    pg_promote_called = any(
        "pg_promote" in str(call.args[0]) for call in conn.fetchval.call_args_list
    )
    assert pg_promote_called

    # is_standby_of remis à None
    set_value_mock.assert_awaited()
    assert set_value_mock.await_args.args[2] is None

    # Audit log écrit
    audit_mock.assert_awaited_once()
    assert audit_mock.await_args.args[1] == "replication.promoted_to_master"


@pytest.mark.asyncio
async def test_promote_refuses_if_not_in_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tentative de promote alors qu'on est déjà primary → NotInStandbyModeError."""
    from app.services.streaming_replication import (
        NotInStandbyModeError,
        promote_standby_to_master,
    )

    conn = _build_conn(fetchval_returns=[False])  # not in recovery = already primary

    with pytest.raises(NotInStandbyModeError):
        await promote_standby_to_master(conn, actor_user_id=None)


@pytest.mark.asyncio
async def test_promote_raises_if_still_in_recovery_after_pg_promote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg_promote retourne True mais le serveur reste en recovery → PromotionFailedError."""
    from app.services.streaming_replication import (
        PromotionFailedError,
        promote_standby_to_master,
    )

    # in_recovery=True, pg_promote=True, in_recovery toujours True après
    conn = _build_conn(fetchval_returns=[True, True, True])
    monkeypatch.setattr(
        "app.db.repositories.system_metadata.get_value",
        AsyncMock(return_value="https://m/"),
    )

    with pytest.raises(PromotionFailedError):
        await promote_standby_to_master(conn, actor_user_id=None)
