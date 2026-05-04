"""Algorithme de rotation GFS (Grandfather-Father-Son) — LOT_14."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from app.db.repositories.backups import BackupRecord


@dataclass
class RotationAction:
    action: str  # "delete" | "promote"
    snapshot_id: UUID
    new_tier: str | None = None
    reason: str | None = None


@dataclass
class GFSRetention:
    hourly: int = 24
    daily: int = 7
    weekly: int = 4
    monthly: int = 12
    yearly: int = 5


@dataclass
class GFSPolicy:
    interval_minutes: int = 0
    retention: GFSRetention = None  # type: ignore[assignment]
    push_remote_after_snapshot: bool = False
    remote_destinations_to_push: list[str] = None  # type: ignore[assignment]
    skip_if_no_change: bool = True

    def __post_init__(self) -> None:
        if self.retention is None:
            self.retention = GFSRetention()
        if self.remote_destinations_to_push is None:
            self.remote_destinations_to_push = []

    @classmethod
    def from_dict(cls, d: dict) -> "GFSPolicy":
        ret_raw = d.get("retention", {})
        retention = GFSRetention(
            hourly=ret_raw.get("hourly", 24),
            daily=ret_raw.get("daily", 7),
            weekly=ret_raw.get("weekly", 4),
            monthly=ret_raw.get("monthly", 12),
            yearly=ret_raw.get("yearly", 5),
        )
        return cls(
            interval_minutes=d.get("interval_minutes", 0),
            retention=retention,
            push_remote_after_snapshot=d.get("push_remote_after_snapshot", False),
            remote_destinations_to_push=d.get("remote_destinations_to_push", []),
            skip_if_no_change=d.get("skip_if_no_change", True),
        )

    def to_dict(self) -> dict:
        return {
            "interval_minutes": self.interval_minutes,
            "retention": {
                "hourly": self.retention.hourly,
                "daily": self.retention.daily,
                "weekly": self.retention.weekly,
                "monthly": self.retention.monthly,
                "yearly": self.retention.yearly,
            },
            "push_remote_after_snapshot": self.push_remote_after_snapshot,
            "remote_destinations_to_push": self.remote_destinations_to_push,
            "skip_if_no_change": self.skip_if_no_change,
        }


_TIERS = ["hourly", "daily", "weekly", "monthly", "yearly"]
_RETENTION_ATTR = {
    "hourly": "hourly",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "yearly": "yearly",
}


def _week_monday(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())


def rotate(snapshots: list[BackupRecord], policy: GFSPolicy) -> list[RotationAction]:
    """Calcule les actions de rotation GFS.

    Promotion AVANT suppression pour ne jamais perdre un candidat.
    Ne touche pas les backups manuels (tier is None + filename harpocrate-backup-*).
    """
    actions: list[RotationAction] = []

    by_tier: dict[str, list[BackupRecord]] = {t: [] for t in _TIERS}
    for s in snapshots:
        if s.tier in by_tier:
            by_tier[s.tier].append(s)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    # ─── Promotions (avant suppressions) ─────────────────────────────────────

    # hourly → daily : si pas de daily pour hier, promouvoir le hourly le + récent d'hier
    if not any(s.created_at.date() == yesterday for s in by_tier["daily"]):
        candidate = next(
            (s for s in sorted(by_tier["hourly"], key=lambda s: s.created_at, reverse=True)
             if s.created_at.date() == yesterday),
            None,
        )
        if candidate:
            actions.append(RotationAction(
                action="promote", snapshot_id=candidate.id,
                new_tier="daily",
                reason=f"daily promotion for {yesterday.isoformat()}",
            ))

    # daily → weekly : chaque lundi pour la semaine précédente
    if today.weekday() == 0:  # lundi
        last_monday = _week_monday(yesterday)
        if not any(_week_monday(s.created_at.date()) == last_monday for s in by_tier["weekly"]):
            candidate = next(
                (s for s in sorted(by_tier["daily"], key=lambda s: s.created_at, reverse=True)
                 if _week_monday(s.created_at.date()) == last_monday),
                None,
            )
            if candidate:
                actions.append(RotationAction(
                    action="promote", snapshot_id=candidate.id,
                    new_tier="weekly",
                    reason=f"weekly promotion for week of {last_monday.isoformat()}",
                ))

    # weekly → monthly : 1er du mois pour le mois précédent
    if today.day == 1:
        last_month = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
        if not any(
            s.created_at.date().year == last_month.year
            and s.created_at.date().month == last_month.month
            for s in by_tier["monthly"]
        ):
            candidate = next(
                (s for s in sorted(by_tier["weekly"], key=lambda s: s.created_at, reverse=True)
                 if s.created_at.date().year == last_month.year
                 and s.created_at.date().month == last_month.month),
                None,
            )
            if candidate:
                actions.append(RotationAction(
                    action="promote", snapshot_id=candidate.id,
                    new_tier="monthly",
                    reason=f"monthly promotion for {last_month.strftime('%Y-%m')}",
                ))

    # monthly → yearly : 1er janvier pour l'année précédente
    if today.day == 1 and today.month == 1:
        last_year = today.year - 1
        if not any(s.created_at.date().year == last_year for s in by_tier["yearly"]):
            candidate = next(
                (s for s in sorted(by_tier["monthly"], key=lambda s: s.created_at, reverse=True)
                 if s.created_at.date().year == last_year),
                None,
            )
            if candidate:
                actions.append(RotationAction(
                    action="promote", snapshot_id=candidate.id,
                    new_tier="yearly",
                    reason=f"yearly promotion for {last_year}",
                ))

    # Track promoted IDs so we don't delete them
    promoted_ids = {a.snapshot_id for a in actions if a.action == "promote"}

    # ─── Suppressions ─────────────────────────────────────────────────────────
    for tier in _TIERS:
        retention = getattr(policy.retention, _RETENTION_ATTR[tier])
        if retention <= 0:
            continue
        items = sorted(by_tier[tier], key=lambda s: s.created_at, reverse=True)
        to_delete = items[retention:]
        for s in to_delete:
            if s.id not in promoted_ids:
                actions.append(RotationAction(
                    action="delete", snapshot_id=s.id,
                    reason=f"exceeded {tier} retention ({retention})",
                ))

    return actions
