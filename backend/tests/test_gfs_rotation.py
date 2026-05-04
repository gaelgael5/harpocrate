"""Tests de la logique de rotation GFS — LOT_14."""
from __future__ import annotations

import datetime
import uuid

import pytest

from app.db.repositories.backups import BackupRecord
from app.services.gfs_rotation import GFSPolicy, GFSRetention, rotate

_UTC = datetime.UTC


def _snap(
    *,
    tier: str,
    created_at: datetime.datetime,
    id: str | None = None,
) -> BackupRecord:
    return BackupRecord(
        id=uuid.UUID(id) if id else uuid.uuid4(),
        filename=f"harpocrate-snapshot-{created_at.strftime('%Y-%m-%d-%H-%M-%S')}.tar.age",
        size_bytes=1000,
        checksum_sha256="abc",
        age_recipient="age1...",
        manifest={},
        description=None,
        created_at=created_at,
        created_by_user_id=None,
        imported=False,
        tier=tier,
    )


def _policy(
    *,
    hourly: int = 24,
    daily: int = 7,
    weekly: int = 4,
    monthly: int = 12,
    yearly: int = 5,
) -> GFSPolicy:
    return GFSPolicy(
        interval_minutes=60,
        retention=GFSRetention(
            hourly=hourly,
            daily=daily,
            weekly=weekly,
            monthly=monthly,
            yearly=yearly,
        ),
    )


def test_no_snapshots_returns_no_actions() -> None:
    actions = rotate([], _policy())
    assert actions == []


def test_rotation_trims_hourly() -> None:
    """Avec retention=3 et 5 snapshots horaires, on en supprime 2."""
    now = datetime.datetime(2026, 5, 3, 15, 0, tzinfo=_UTC)
    snaps = [
        _snap(tier="hourly", created_at=now - datetime.timedelta(hours=i))
        for i in range(5)
    ]
    actions = rotate(snaps, _policy(hourly=3))

    deletes = [a for a in actions if a.action == "delete"]
    assert len(deletes) == 2
    # Les 2 plus vieux sont supprimés
    oldest_ids = {snaps[3].id, snaps[4].id}
    assert {a.snapshot_id for a in deletes} == oldest_ids


def test_rotation_does_not_touch_manual_backups() -> None:
    """Les backups manuels (tier=None) ne sont jamais supprimés."""
    from app.db.repositories.backups import BackupRecord
    manual = BackupRecord(
        id=uuid.uuid4(),
        filename="harpocrate-backup-2026-01-01-12-00-00.tar.age",
        size_bytes=1000,
        checksum_sha256="abc",
        age_recipient="age1...",
        manifest={},
        description=None,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=_UTC),
        created_by_user_id=None,
        imported=False,
        tier=None,  # manuel
    )
    actions = rotate([manual], _policy())
    assert all(a.snapshot_id != manual.id for a in actions if a.action == "delete")


def test_promoted_snapshot_not_deleted() -> None:
    """Un snapshot promu ne doit pas être supprimé dans le même cycle."""
    yesterday = datetime.datetime(2026, 5, 2, 14, 0, tzinfo=_UTC)
    today = datetime.datetime(2026, 5, 3, 12, 0, tzinfo=_UTC)

    # 3 hourly dont 1 d'hier qui devrait être promu en daily
    hourly_snaps = [
        _snap(tier="hourly", created_at=yesterday),  # candidat promotion
        _snap(tier="hourly", created_at=today - datetime.timedelta(hours=1)),
        _snap(tier="hourly", created_at=today - datetime.timedelta(hours=2)),
    ]
    # Avec retention=2, le plus vieux (yesterday) serait normalement supprimé
    actions = rotate(hourly_snaps, _policy(hourly=2))

    promoted_ids = {a.snapshot_id for a in actions if a.action == "promote"}
    deleted_ids = {a.snapshot_id for a in actions if a.action == "delete"}

    # Le snapshot promu ne doit PAS être dans les suppressions
    assert promoted_ids.isdisjoint(deleted_ids)


def test_policy_from_dict_roundtrip() -> None:
    d = {
        "interval_minutes": 120,
        "retention": {"hourly": 48, "daily": 14, "weekly": 8, "monthly": 24, "yearly": 10},
        "push_remote_after_snapshot": True,
        "remote_destinations_to_push": ["s3"],
        "skip_if_no_change": False,
    }
    policy = GFSPolicy.from_dict(d)
    assert policy.interval_minutes == 120
    assert policy.retention.hourly == 48
    assert policy.push_remote_after_snapshot is True
    assert policy.skip_if_no_change is False
    assert policy.to_dict() == d
