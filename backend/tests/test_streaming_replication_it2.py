"""Tests itération 2 du service streaming_replication.

Couvre :
  - tcp_ping (mock asyncio.open_connection)
  - get/set lag_thresholds (avec validation)
  - check_lag_threshold avec hystérésis (1 seule anomalie ouverte par
    node+severity)
  - purge_old_observations
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


# ─── tcp_ping ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tcp_ping_success() -> None:
    from app.services.streaming_replication import tcp_ping

    fake_reader = MagicMock()
    fake_writer = MagicMock()
    fake_writer.close = MagicMock()
    fake_writer.wait_closed = AsyncMock()

    async def _fake_open(host: str, port: int) -> Any:
        return fake_reader, fake_writer

    with patch("asyncio.open_connection", _fake_open):
        result = await tcp_ping("192.168.10.200", 5432)

    assert result.ok is True
    assert result.error is None
    assert result.latency_ms is not None and result.latency_ms >= 0
    fake_writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_tcp_ping_timeout() -> None:
    from app.services.streaming_replication import tcp_ping

    async def _slow_open(host: str, port: int) -> Any:
        await asyncio.sleep(5)
        raise AssertionError("should have timed out")

    with patch("asyncio.open_connection", _slow_open):
        result = await tcp_ping("10.255.255.1", 5432, timeout=0.1)

    assert result.ok is False
    assert "timeout" in (result.error or "").lower()
    assert result.latency_ms is None


@pytest.mark.asyncio
async def test_tcp_ping_connection_refused() -> None:
    from app.services.streaming_replication import tcp_ping

    async def _refused(host: str, port: int) -> Any:
        raise OSError("Connection refused")

    with patch("asyncio.open_connection", _refused):
        result = await tcp_ping("127.0.0.1", 9)

    assert result.ok is False
    assert "Connection refused" in (result.error or "")


# ─── lag thresholds ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_lag_thresholds_returns_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    async def _none(_c: Any, _k: str) -> Any:
        return None

    monkeypatch.setattr(svc.meta_repo, "get_value", _none)

    conn = MagicMock()
    t = await svc.get_lag_thresholds(conn)
    assert t.warning_bytes == 64 * 1024 * 1024
    assert t.critical_bytes == 512 * 1024 * 1024


@pytest.mark.asyncio
async def test_get_lag_thresholds_returns_stored_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    async def _stored(_c: Any, _k: str) -> Any:
        return {"warning_bytes": 1024, "critical_bytes": 4096}

    monkeypatch.setattr(svc.meta_repo, "get_value", _stored)

    conn = MagicMock()
    t = await svc.get_lag_thresholds(conn)
    assert t.warning_bytes == 1024
    assert t.critical_bytes == 4096


@pytest.mark.asyncio
async def test_set_lag_thresholds_rejects_negative() -> None:
    from app.services import streaming_replication as svc

    conn = MagicMock()
    with pytest.raises(ValueError, match="non-negative"):
        await svc.set_lag_thresholds(conn, warning_bytes=-1, critical_bytes=10)


@pytest.mark.asyncio
async def test_set_lag_thresholds_rejects_warning_above_critical() -> None:
    from app.services import streaming_replication as svc

    conn = MagicMock()
    with pytest.raises(ValueError, match="must be <="):
        await svc.set_lag_thresholds(
            conn, warning_bytes=1000, critical_bytes=500
        )


@pytest.mark.asyncio
async def test_set_lag_thresholds_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    written: dict[str, Any] = {}

    async def _set(_c: Any, key: str, value: Any) -> None:
        written["key"] = key
        written["value"] = value

    monkeypatch.setattr(svc.meta_repo, "set_value", _set)

    conn = MagicMock()
    new = await svc.set_lag_thresholds(
        conn, warning_bytes=2048, critical_bytes=8192
    )
    assert new.warning_bytes == 2048
    assert written["key"] == svc.LAG_THRESHOLDS_KEY
    assert written["value"] == {"warning_bytes": 2048, "critical_bytes": 8192}


# ─── check_lag_threshold + hystérésis ────────────────────────────────────────


def _make_thresholds() -> Any:
    from app.services.streaming_replication import LagThresholds
    return LagThresholds(warning_bytes=1000, critical_bytes=10000)


@pytest.mark.asyncio
async def test_check_lag_no_threshold_no_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    reported = []

    async def _report(*a: Any, **kw: Any) -> int:
        reported.append(kw)
        return 1

    monkeypatch.setattr(svc.anomaly_svc, "report", _report)

    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    severity = await svc.check_lag_threshold(
        conn,
        node_id=uuid4(),
        node_label="test",
        lag_bytes=500,  # < warning
        thresholds=_make_thresholds(),
    )
    assert severity is None
    assert len(reported) == 0


@pytest.mark.asyncio
async def test_check_lag_warning_creates_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    reported = []

    async def _report(*a: Any, **kw: Any) -> int:
        reported.append(kw)
        return 1

    monkeypatch.setattr(svc.anomaly_svc, "report", _report)

    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)  # pas d'anomalie ouverte
    severity = await svc.check_lag_threshold(
        conn,
        node_id=uuid4(),
        node_label="test",
        lag_bytes=5000,  # > warning, < critical
        thresholds=_make_thresholds(),
    )
    assert severity == "warning"
    assert len(reported) == 1
    assert reported[0]["severity"] == "warning"
    assert reported[0]["anomaly_type"] == "replication_lag_warning"


@pytest.mark.asyncio
async def test_check_lag_critical_takes_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    reported = []

    async def _report(*a: Any, **kw: Any) -> int:
        reported.append(kw)
        return 1

    monkeypatch.setattr(svc.anomaly_svc, "report", _report)

    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    severity = await svc.check_lag_threshold(
        conn,
        node_id=uuid4(),
        node_label="test",
        lag_bytes=20000,  # > critical
        thresholds=_make_thresholds(),
    )
    assert severity == "critical"
    assert len(reported) == 1
    assert reported[0]["severity"] == "critical"
    # Pas de warning créé en parallèle.
    assert all(r["anomaly_type"] != "replication_lag_warning" for r in reported)


@pytest.mark.asyncio
async def test_check_lag_hysteresis_skips_when_anomaly_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si une anomalie warning non-ack existe déjà pour ce node → on ne crée
    pas un doublon. C'est l'hystérésis."""
    from app.services import streaming_replication as svc

    reported = []

    async def _report(*a: Any, **kw: Any) -> int:
        reported.append(kw)
        return 1

    monkeypatch.setattr(svc.anomaly_svc, "report", _report)

    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=1)  # anomalie déjà ouverte
    severity = await svc.check_lag_threshold(
        conn,
        node_id=uuid4(),
        node_label="test",
        lag_bytes=5000,
        thresholds=_make_thresholds(),
    )
    # On retourne quand même la severity (le caller veut savoir "il y a un pb")
    # mais on ne re-crée pas d'anomalie.
    assert severity == "warning"
    assert len(reported) == 0


@pytest.mark.asyncio
async def test_check_lag_none_returns_none() -> None:
    """lag_bytes=None (state disconnected/unknown) → pas de check."""
    from app.services import streaming_replication as svc

    conn = MagicMock()
    severity = await svc.check_lag_threshold(
        conn,
        node_id=uuid4(),
        node_label="test",
        lag_bytes=None,
        thresholds=_make_thresholds(),
    )
    assert severity is None


# ─── purge_old_observations ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_old_observations_returns_deleted_count() -> None:
    from app.services.streaming_replication import purge_old_observations

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="DELETE 42")

    n = await purge_old_observations(conn, days=7)
    assert n == 42

    # On vérifie que le DELETE a bien été appelé avec le bon interval.
    args = conn.execute.await_args.args
    assert "7 days" in args[1]


@pytest.mark.asyncio
async def test_purge_handles_zero_deletions() -> None:
    from app.services.streaming_replication import purge_old_observations

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="DELETE 0")

    n = await purge_old_observations(conn)
    assert n == 0
