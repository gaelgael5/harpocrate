"""Tests des stratégies de réplication (LOT_20)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


@pytest.mark.asyncio
async def test_none_strategy_returns_ok_with_no_replicas() -> None:
    from app.core.replication import NoneStrategy
    s = NoneStrategy()
    status = await s.get_status()
    assert status["type"] == "none"
    assert status["status"] == "ok"
    assert status["replicas"] == []
    assert status["primary"] is None


def test_patroni_strategy_requires_at_least_one_url() -> None:
    from app.core.replication import PatroniStrategy
    with pytest.raises(ValueError, match="patroni_api_urls"):
        PatroniStrategy({"patroni_api_urls": []})
    with pytest.raises(ValueError, match="patroni_api_urls"):
        PatroniStrategy({})


def test_patroni_strategy_rejects_non_str_urls() -> None:
    from app.core.replication import PatroniStrategy
    with pytest.raises(ValueError, match="patroni_api_urls"):
        PatroniStrategy({"patroni_api_urls": [123, "valid"]})


@pytest.mark.asyncio
async def test_patroni_status_aggregates_nodes() -> None:
    """get_status interroge les 2 nœuds, identifie primary + replicas."""
    from app.core.replication import PatroniStrategy

    primary_payload = {
        "role": "master",
        "state": "running",
        "timeline": 4,
    }
    replica_payload = {
        "role": "replica",
        "state": "streaming",
        "timeline": 4,
        "replication_state": {"lag": 0},
    }

    def _resp(payload: dict[str, Any]) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.json = MagicMock(return_value=payload)
        return r

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[_resp(primary_payload), _resp(replica_payload)])

    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return fake_client

        async def __aexit__(self, *_a: Any) -> None:
            pass

    with patch("app.core.replication.httpx.AsyncClient", return_value=_Ctx()):
        s = PatroniStrategy({
            "patroni_api_urls": ["http://p:8008", "http://r:8008"],
        })
        status = await s.get_status()

    assert status["type"] == "patroni"
    assert status["status"] == "ok"
    assert status["primary"]["role"] == "master"
    assert len(status["replicas"]) == 1
    assert status["replicas"][0]["lag"] == 0


@pytest.mark.asyncio
async def test_patroni_status_degraded_when_no_primary() -> None:
    from app.core.replication import PatroniStrategy

    def _bad() -> MagicMock:
        r = MagicMock()
        r.status_code = 500
        r.json = MagicMock(return_value={})
        return r

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[_bad(), _bad()])

    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return fake_client

        async def __aexit__(self, *_a: Any) -> None:
            pass

    with patch("app.core.replication.httpx.AsyncClient", return_value=_Ctx()):
        s = PatroniStrategy({"patroni_api_urls": ["http://a:8008", "http://b:8008"]})
        status = await s.get_status()

    assert status["status"] == "degraded"
    assert status["primary"] is None


def test_build_strategy_factory_returns_correct_subclass() -> None:
    from app.core.replication import (
        NoneStrategy,
        PatroniStrategy,
        build_strategy,
    )
    assert isinstance(build_strategy(type_="none", config={}), NoneStrategy)
    s = build_strategy(
        type_="patroni",
        config={"patroni_api_urls": ["http://x:8008"]},
    )
    assert isinstance(s, PatroniStrategy)


def test_build_strategy_raises_for_unknown_type() -> None:
    from app.core.replication import build_strategy
    with pytest.raises(ValueError, match="unknown replication strategy"):
        build_strategy(type_="bogus", config={})


def test_build_strategy_raises_not_implemented_for_future_types() -> None:
    from app.core.replication import build_strategy
    with pytest.raises(NotImplementedError):
        build_strategy(type_="harpocrate_sync", config={})
    with pytest.raises(NotImplementedError):
        build_strategy(type_="s3_wal", config={})
