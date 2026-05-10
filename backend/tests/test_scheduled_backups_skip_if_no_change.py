"""Tests du comportement skip-if-no-change de run_schedule.

On mocke conn.fetchval pour piloter exactement les valeurs renvoyées par
`_last_db_change` et `_last_backup_completed_at`. La création réelle du
backup (`create_backup`) est aussi mockée pour ne pas avoir besoin de
PostgreSQL ni de pg_dump.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest


_NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _make_schedule() -> Any:
    """ScheduledBackup DTO local-only minimal."""
    from app.services.scheduled_backups import ScheduledBackup

    return ScheduledBackup(
        id=uuid4(),
        name="Daily 2h",
        cron_expression="0 2 * * *",
        remote_id=None,  # local-only — pas de push à mocker
        miss_threshold_minutes=5,
        enabled=True,
        description=None,
        next_run_at=_NOW.isoformat(),
        last_run_at=None,
        last_run_status=None,
        last_run_error=None,
        remote_id_disconnected_at=None,
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
    )


def _make_conn(*, last_backup_end: datetime | None, last_change: datetime) -> MagicMock:
    """Mock conn dont fetchval renvoie séquentiellement :
    1) last_backup_end (peut être None)
    2) last_change (uniquement appelé si last_backup_end != None)
    """
    conn = MagicMock()
    if last_backup_end is None:
        # Un seul appel à fetchval (pour _last_backup_completed_at) → None
        conn.fetchval = AsyncMock(side_effect=[None])
    else:
        conn.fetchval = AsyncMock(side_effect=[last_backup_end, last_change])
    return conn


@pytest.mark.asyncio
async def test_run_schedule_skipped_when_no_change_since_last_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la base n'a pas bougé depuis le dernier backup → status='skipped'."""
    from app.services import scheduled_backups as svc

    last_backup = _NOW - timedelta(hours=1)
    last_change = _NOW - timedelta(hours=2)  # avant le dernier backup → no change
    conn = _make_conn(last_backup_end=last_backup, last_change=last_change)

    # On veut s'assurer que create_backup n'est PAS appelé
    create_called = False

    async def _spy_create(*a: Any, **kw: Any) -> Any:
        nonlocal create_called
        create_called = True
        return MagicMock(id=UUID("11111111-0000-0000-0000-000000000001"))

    monkeypatch.setattr(svc, "create_backup", _spy_create)

    result = await svc.run_schedule(conn, _make_schedule())

    assert result.status == "skipped"
    assert "no changes since last backup" in (result.error or "")
    assert result.backup_id is None
    assert create_called is False, "create_backup ne doit pas être appelé"


@pytest.mark.asyncio
async def test_run_schedule_proceeds_when_db_changed_since_last_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la base a bougé depuis le dernier backup → run normal (status='ok')."""
    from app.services import scheduled_backups as svc

    last_backup = _NOW - timedelta(hours=2)
    last_change = _NOW - timedelta(minutes=30)  # après le dernier backup → run
    conn = _make_conn(last_backup_end=last_backup, last_change=last_change)

    fake_record = MagicMock()
    fake_record.id = UUID("22222222-0000-0000-0000-000000000001")
    fake_record.filename = "harpocrate-backup-2026-05-10-12-00-00.tar.age"

    async def _spy_create(*a: Any, **kw: Any) -> Any:
        return fake_record

    monkeypatch.setattr(svc, "create_backup", _spy_create)

    result = await svc.run_schedule(conn, _make_schedule())

    assert result.status == "ok"
    assert result.backup_id == fake_record.id


@pytest.mark.asyncio
async def test_run_schedule_proceeds_when_no_previous_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Premier backup (aucun précédent) → on lance toujours."""
    from app.services import scheduled_backups as svc

    conn = _make_conn(last_backup_end=None, last_change=_NOW)

    fake_record = MagicMock()
    fake_record.id = UUID("33333333-0000-0000-0000-000000000001")
    fake_record.filename = "harpocrate-backup-2026-05-10-12-00-00.tar.age"

    async def _spy_create(*a: Any, **kw: Any) -> Any:
        return fake_record

    monkeypatch.setattr(svc, "create_backup", _spy_create)

    result = await svc.run_schedule(conn, _make_schedule())

    assert result.status == "ok"
    assert result.backup_id == fake_record.id


@pytest.mark.asyncio
async def test_run_schedule_skipped_when_change_at_exact_same_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge case : last_change == last_backup_end → on skip (le backup contient déjà la modif)."""
    from app.services import scheduled_backups as svc

    same = _NOW - timedelta(hours=1)
    conn = _make_conn(last_backup_end=same, last_change=same)

    async def _spy_create(*a: Any, **kw: Any) -> Any:
        raise AssertionError("ne doit pas être appelé")

    monkeypatch.setattr(svc, "create_backup", _spy_create)

    result = await svc.run_schedule(conn, _make_schedule())
    assert result.status == "skipped"
