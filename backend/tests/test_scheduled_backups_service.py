"""Tests unitaires du service scheduled_backups (validation cron, miss policy)."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


# ─── validate_cron ───────────────────────────────────────────────────────────


def test_validate_cron_valid_returns_3_occurrences() -> None:
    from app.services.scheduled_backups import validate_cron

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = validate_cron("0 2 * * *", base=base)
    assert res.valid is True
    assert res.error is None
    assert len(res.next_3_occurrences) == 3
    # First occurrence après 12:00 = lendemain 02:00
    assert "2026-01-02T02:00:00" in res.next_3_occurrences[0]


def test_validate_cron_empty_returns_error() -> None:
    from app.services.scheduled_backups import validate_cron

    res = validate_cron("")
    assert res.valid is False
    assert "required" in (res.error or "").lower()
    assert res.next_3_occurrences == []


def test_validate_cron_invalid_syntax_returns_error() -> None:
    from app.services.scheduled_backups import validate_cron

    res = validate_cron("not a cron")
    assert res.valid is False
    assert res.error is not None


def test_validate_cron_accepts_step_syntax() -> None:
    from app.services.scheduled_backups import validate_cron

    res = validate_cron("*/30 * * * *")
    assert res.valid is True
    assert len(res.next_3_occurrences) == 3


# ─── compute_next_run ────────────────────────────────────────────────────────


def test_compute_next_run_returns_tz_aware() -> None:
    from app.services.scheduled_backups import compute_next_run

    after = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run("0 2 * * *", after=after)
    assert nxt.tzinfo is not None
    # Lendemain 02:00 UTC
    assert nxt == datetime(2026, 1, 2, 2, 0, 0, tzinfo=timezone.utc)


# ─── is_miss ─────────────────────────────────────────────────────────────────


def _make_dto(*, next_run_at: str, miss_threshold: int = 5) -> MagicMock:
    dto = MagicMock()
    dto.next_run_at = next_run_at
    dto.miss_threshold_minutes = miss_threshold
    return dto


def test_is_miss_returns_false_for_future_runs() -> None:
    from app.services.scheduled_backups import is_miss

    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    future = (now + timedelta(hours=1)).isoformat()
    assert is_miss(_make_dto(next_run_at=future), now=now) is False


def test_is_miss_returns_false_within_threshold() -> None:
    from app.services.scheduled_backups import is_miss

    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # 3 min de retard, threshold 5 → pas un miss
    barely_late = (now - timedelta(minutes=3)).isoformat()
    assert is_miss(_make_dto(next_run_at=barely_late, miss_threshold=5), now=now) is False


def test_is_miss_returns_true_beyond_threshold() -> None:
    from app.services.scheduled_backups import is_miss

    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # 10 min de retard, threshold 5 → miss
    late = (now - timedelta(minutes=10)).isoformat()
    assert is_miss(_make_dto(next_run_at=late, miss_threshold=5), now=now) is True


def test_is_miss_respects_per_schedule_threshold() -> None:
    from app.services.scheduled_backups import is_miss

    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # 45 min de retard
    late = (now - timedelta(minutes=45)).isoformat()
    # threshold 30 → miss
    assert is_miss(_make_dto(next_run_at=late, miss_threshold=30), now=now) is True
    # threshold 60 → pas un miss
    assert is_miss(_make_dto(next_run_at=late, miss_threshold=60), now=now) is False
