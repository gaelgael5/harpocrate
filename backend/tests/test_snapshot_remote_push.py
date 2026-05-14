"""Tests du push snapshot vers les remote_backup_connection.

On teste `_push_snapshot_to_remotes` et `_push_snapshot_to_one_remote` du
SnapshotScheduler avec mocks asyncpg + provider — sans toucher à pg_dump
ni à un vrai serveur SFTP.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

_REMOTE_ID_1 = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_REMOTE_ID_2 = UUID("aaaaaaaa-0000-0000-0000-000000000002")


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")
    monkeypatch.setenv("HARPOCRATE_BACKUP_LOCAL_PATH", "/tmp")


def _make_backup_record() -> Any:
    rec = MagicMock()
    rec.id = uuid4()
    rec.filename = "harpocrate-snapshot-2026-05-10-12-00-00.tar.age"
    rec.size_bytes = 1024
    return rec


def _make_remote_dto(
    *,
    name: str = "OVH",
    kind: str = "sftp",
    snapshots_path: str | None = "/snapshots",
) -> Any:
    dto = MagicMock()
    dto.name = name
    dto.kind = kind
    config: dict[str, Any] = {"host": "h", "port": 22}
    if snapshots_path is not None:
        if kind == "s3":
            config["prefix_snapshots"] = snapshots_path
        else:
            config["remote_path_snapshots"] = snapshots_path
    dto.config = config
    return dto


def _scheduler_with_pool() -> Any:
    """Construit un SnapshotScheduler avec un pool factice."""
    from app.services.snapshot_scheduler import SnapshotScheduler

    return SnapshotScheduler()


@pytest.mark.asyncio
async def test_push_to_remotes_skips_legacy_string_dest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """remote_destinations_to_push contient 's3' (legacy) → log warning + skip,
    aucun push tenté. Aucune anomalie créée car ce n'est pas un échec — c'est
    juste de la config legacy à migrer."""
    from app.services import system_anomalies as anomaly_svc
    from app.services.gfs_rotation import GFSPolicy

    sched = _scheduler_with_pool()
    backup = _make_backup_record()
    policy = GFSPolicy(
        push_remote_after_snapshot=True,
        remote_destinations_to_push=["s3"],  # legacy
    )

    anomaly_called = False

    async def _spy_anomaly(*a: Any, **kw: Any) -> int:
        nonlocal anomaly_called
        anomaly_called = True
        return 1

    monkeypatch.setattr(anomaly_svc, "report", _spy_anomaly)

    conn = MagicMock()
    results = await sched._push_snapshot_to_remotes(conn, backup=backup, policy=policy)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["skipped"] == "legacy"
    assert anomaly_called is False, "legacy 's3' n'est pas une anomalie"


@pytest.mark.asyncio
async def test_push_to_remotes_success_with_one_uuid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """1 UUID valide → resolve, push, success. Pas d'anomalie."""
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc
    from app.services import snapshot_scheduler as snap_mod
    from app.services import system_anomalies as anomaly_svc
    from app.services.gfs_rotation import GFSPolicy

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))
    sched = _scheduler_with_pool()
    backup = _make_backup_record()
    (tmp_path / backup.filename).write_bytes(b"snapshot-bytes")

    policy = GFSPolicy(
        push_remote_after_snapshot=True,
        remote_destinations_to_push=[str(_REMOTE_ID_1)],
    )

    async def _get_conn(_c: Any, _id: UUID) -> Any:
        return _make_remote_dto()

    async def _get_creds(_c: Any, _id: UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _get_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _get_creds)

    fake_provider = MagicMock()
    fake_provider.upload_stream = AsyncMock(return_value=14)
    monkeypatch.setattr(snap_mod, "get_provider", lambda *_a, **_kw: fake_provider)

    anomaly_called = False

    async def _spy_anomaly(*a: Any, **kw: Any) -> int:
        nonlocal anomaly_called
        anomaly_called = True
        return 1

    monkeypatch.setattr(anomaly_svc, "report", _spy_anomaly)

    conn = MagicMock()
    results = await sched._push_snapshot_to_remotes(conn, backup=backup, policy=policy)

    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0]["bytes"] == 14
    assert anomaly_called is False
    fake_provider.upload_stream.assert_awaited_once_with(
        "/snapshots", backup.filename, fake_provider.upload_stream.call_args.args[2]
    )


@pytest.mark.asyncio
async def test_push_partial_failure_creates_anomaly_continues_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """2 cibles : la première échoue → anomalie créée, la seconde réussit."""
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc
    from app.services import snapshot_scheduler as snap_mod
    from app.services import system_anomalies as anomaly_svc
    from app.services.gfs_rotation import GFSPolicy
    from app.services.remote_backup_providers import RemoteBackupProviderError

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))
    sched = _scheduler_with_pool()
    backup = _make_backup_record()
    (tmp_path / backup.filename).write_bytes(b"x" * 32)

    policy = GFSPolicy(
        push_remote_after_snapshot=True,
        remote_destinations_to_push=[str(_REMOTE_ID_1), str(_REMOTE_ID_2)],
    )

    async def _get_conn(_c: Any, rid: UUID) -> Any:
        return _make_remote_dto(name="OVH" if rid == _REMOTE_ID_1 else "AWS")

    async def _get_creds(_c: Any, _id: UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _get_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _get_creds)

    # Provider qui échoue pour _REMOTE_ID_1 et réussit pour _REMOTE_ID_2.
    # Comme get_provider reçoit (kind, config, creds) et qu'on a le même config
    # pour les deux, on distingue via un compteur d'appel.
    call_count = {"n": 0}

    def _provider_factory(*_a: Any, **_kw: Any) -> Any:
        call_count["n"] += 1
        p = MagicMock()
        if call_count["n"] == 1:
            p.upload_stream = AsyncMock(side_effect=RemoteBackupProviderError("net err"))
        else:
            p.upload_stream = AsyncMock(return_value=32)
        return p

    monkeypatch.setattr(snap_mod, "get_provider", _provider_factory)

    anomalies: list[dict[str, Any]] = []

    async def _spy_anomaly(_conn: Any, **kw: Any) -> int:
        anomalies.append(kw)
        return len(anomalies)

    monkeypatch.setattr(anomaly_svc, "report", _spy_anomaly)

    conn = MagicMock()
    results = await sched._push_snapshot_to_remotes(conn, backup=backup, policy=policy)

    assert len(results) == 2
    assert results[0]["success"] is False, "1er push doit échouer"
    assert results[1]["success"] is True, "2e push doit réussir"
    assert len(anomalies) == 1, "1 seule anomalie pour le 1er push raté"
    assert anomalies[0]["severity"] == "warning"
    assert anomalies[0]["source"] == "snapshot_remote_push"
    assert anomalies[0]["anomaly_type"] == "snapshot_remote_push_failed"


@pytest.mark.asyncio
async def test_push_to_remote_no_snapshots_path_creates_anomaly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Connexion remote sans `remote_path_snapshots` configuré → anomalie."""
    from app.core import config as cfg
    from app.services import remote_backup_connections as remote_svc
    from app.services import system_anomalies as anomaly_svc
    from app.services.gfs_rotation import GFSPolicy

    monkeypatch.setattr(cfg.settings, "backup_local_path", str(tmp_path))
    sched = _scheduler_with_pool()
    backup = _make_backup_record()

    policy = GFSPolicy(
        push_remote_after_snapshot=True,
        remote_destinations_to_push=[str(_REMOTE_ID_1)],
    )

    async def _get_conn(_c: Any, _id: UUID) -> Any:
        return _make_remote_dto(snapshots_path=None)  # pas configuré

    async def _get_creds(_c: Any, _id: UUID) -> dict[str, Any]:
        return {"username": "u", "password": "p"}

    monkeypatch.setattr(remote_svc, "get_connection", _get_conn)
    monkeypatch.setattr(remote_svc, "get_decrypted_credentials", _get_creds)

    anomalies: list[dict[str, Any]] = []

    async def _spy_anomaly(_conn: Any, **kw: Any) -> int:
        anomalies.append(kw)
        return len(anomalies)

    monkeypatch.setattr(anomaly_svc, "report", _spy_anomaly)

    conn = MagicMock()
    results = await sched._push_snapshot_to_remotes(conn, backup=backup, policy=policy)

    assert results[0]["error"] == "no_snapshots_path"
    assert len(anomalies) == 1
    assert anomalies[0]["anomaly_type"] == "snapshot_remote_no_snapshots_path"


@pytest.mark.asyncio
async def test_push_to_remote_not_found_creates_anomaly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """remote_id pointe vers une connexion supprimée → anomalie."""
    from app.services import remote_backup_connections as remote_svc
    from app.services import system_anomalies as anomaly_svc
    from app.services.gfs_rotation import GFSPolicy

    sched = _scheduler_with_pool()
    backup = _make_backup_record()

    policy = GFSPolicy(
        push_remote_after_snapshot=True,
        remote_destinations_to_push=[str(_REMOTE_ID_1)],
    )

    async def _get_conn(_c: Any, _id: UUID) -> Any:
        return None  # introuvable

    monkeypatch.setattr(remote_svc, "get_connection", _get_conn)

    anomalies: list[dict[str, Any]] = []

    async def _spy_anomaly(_conn: Any, **kw: Any) -> int:
        anomalies.append(kw)
        return len(anomalies)

    monkeypatch.setattr(anomaly_svc, "report", _spy_anomaly)

    conn = MagicMock()
    results = await sched._push_snapshot_to_remotes(conn, backup=backup, policy=policy)

    assert results[0]["error"] == "remote_not_found"
    assert anomalies[0]["anomaly_type"] == "snapshot_remote_not_found"


# ─── Lock partagé ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_global_backup_lock_is_singleton() -> None:
    """get_global_backup_lock() retourne toujours le même Lock."""
    from app.services.backup_lock import get_global_backup_lock

    a = get_global_backup_lock()
    b = get_global_backup_lock()
    assert a is b, "le lock doit être singleton (sinon pas de sérialisation)"


@pytest.mark.asyncio
async def test_scheduled_backups_scheduler_uses_global_lock() -> None:
    """Le scheduler des sauvegardes planifiées utilise le lock global."""
    from app.services.backup_lock import get_global_backup_lock
    from app.services.scheduled_backups_scheduler import ScheduledBackupsScheduler

    sched = ScheduledBackupsScheduler()
    assert sched.run_lock is get_global_backup_lock()
