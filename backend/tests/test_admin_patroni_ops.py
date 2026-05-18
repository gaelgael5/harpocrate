"""Tests des endpoints Patroni switchover/reinit/pause/resume — A-9.

Endpoints :
- POST /v1/admin/replication/patroni/switchover (body : candidate_name?, confirmation="SWITCHOVER")
- POST /v1/admin/replication/patroni/reinit (body : member_url, confirmation="REINIT")
- POST /v1/admin/replication/patroni/pause
- POST /v1/admin/replication/patroni/resume

Strategie de mock : on patche `svc.get_active` pour retourner une
PatroniStrategy avec des methodes mockees (pas de vrai appel HTTP a
Patroni).
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(backup)


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}})
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


def _make_conn() -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    class _TxCtx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            pass

    conn.transaction = MagicMock(return_value=_TxCtx())
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _make_patroni_mock(
    *,
    switchover_result: dict | None = None,
    switchover_exc: Exception | None = None,
    reinit_result: dict | None = None,
    reinit_exc: Exception | None = None,
    pause_result: dict | None = None,
    resume_result: dict | None = None,
) -> MagicMock:
    """Fabrique une PatroniStrategy mockee."""
    from app.core.replication import PatroniStrategy

    strategy = MagicMock(spec=PatroniStrategy)
    if switchover_exc:
        strategy.switchover = AsyncMock(side_effect=switchover_exc)
    else:
        strategy.switchover = AsyncMock(
            return_value=switchover_result or {"ok": True, "leader_name": "pg1"}
        )
    if reinit_exc:
        strategy.reinitialize_member = AsyncMock(side_effect=reinit_exc)
    else:
        strategy.reinitialize_member = AsyncMock(
            return_value=reinit_result or {"ok": True, "member_url": "https://pg2:8008"}
        )
    strategy.pause = AsyncMock(
        return_value=pause_result or {"ok": True, "paused": True}
    )
    strategy.resume = AsyncMock(
        return_value=resume_result or {"ok": True, "paused": False}
    )
    return strategy


# ─── Switchover ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switchover_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            "/v1/admin/replication/patroni/switchover",
            headers=_user_header(),
            json={"confirmation": "SWITCHOVER"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_switchover_requires_confirmation_string() -> None:
    """Confirmation != SWITCHOVER -> 400."""
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            "/v1/admin/replication/patroni/switchover",
            headers=_admin_header(),
            json={"confirmation": "yes"},
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_confirmation"


@pytest.mark.asyncio
async def test_switchover_409_when_no_active_strategy() -> None:
    conn = _make_conn()
    with patch("app.services.replication.get_active", AsyncMock(return_value=None)):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/switchover",
                headers=_admin_header(),
                json={"confirmation": "SWITCHOVER"},
            )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "no_active_strategy"


@pytest.mark.asyncio
async def test_switchover_409_when_active_strategy_not_patroni() -> None:
    """Strategie active != Patroni (ex: streaming_async) -> 409."""
    from app.core.replication import NoneStrategy

    conn = _make_conn()
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), NoneStrategy())),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/switchover",
                headers=_admin_header(),
                json={"confirmation": "SWITCHOVER"},
            )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "patroni_not_active"


@pytest.mark.asyncio
async def test_switchover_happy_path() -> None:
    conn = _make_conn()
    strategy = _make_patroni_mock()
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), strategy)),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/switchover",
                headers=_admin_header(),
                json={"confirmation": "SWITCHOVER", "candidate_name": "pg2"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    strategy.switchover.assert_awaited_once()
    # Audit insert appele
    assert conn.execute.await_count >= 1


@pytest.mark.asyncio
async def test_switchover_502_on_patroni_error() -> None:
    from app.core.replication import PatroniOperationError

    conn = _make_conn()
    strategy = _make_patroni_mock(
        switchover_exc=PatroniOperationError("switchover_failed", "etcd unreachable"),
    )
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), strategy)),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/switchover",
                headers=_admin_header(),
                json={"confirmation": "SWITCHOVER"},
            )
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "switchover_failed"


# ─── Reinit ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reinit_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            "/v1/admin/replication/patroni/reinit",
            headers=_user_header(),
            json={
                "confirmation": "REINIT",
                "member_url": "https://pg2:8008",
            },
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reinit_requires_confirmation() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            "/v1/admin/replication/patroni/reinit",
            headers=_admin_header(),
            json={"confirmation": "yes", "member_url": "https://pg2:8008"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reinit_happy_path() -> None:
    conn = _make_conn()
    strategy = _make_patroni_mock()
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), strategy)),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/reinit",
                headers=_admin_header(),
                json={
                    "confirmation": "REINIT",
                    "member_url": "https://pg2:8008",
                },
            )
    assert r.status_code == 200
    strategy.reinitialize_member.assert_awaited_once_with("https://pg2:8008")


@pytest.mark.asyncio
async def test_reinit_refuses_leader() -> None:
    """Si la strategie refuse (cannot_reinit_leader) -> 502."""
    from app.core.replication import PatroniOperationError

    conn = _make_conn()
    strategy = _make_patroni_mock(
        reinit_exc=PatroniOperationError(
            "cannot_reinit_leader", "Refusing to reinitialize the current leader"
        ),
    )
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), strategy)),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/reinit",
                headers=_admin_header(),
                json={
                    "confirmation": "REINIT",
                    "member_url": "https://pg1:8008",
                },
            )
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "cannot_reinit_leader"


# ─── Pause / Resume ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            "/v1/admin/replication/patroni/pause", headers=_user_header()
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_pause_happy_path() -> None:
    conn = _make_conn()
    strategy = _make_patroni_mock()
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), strategy)),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/pause", headers=_admin_header()
            )
    assert r.status_code == 200
    assert r.json()["paused"] is True
    strategy.pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_happy_path() -> None:
    conn = _make_conn()
    strategy = _make_patroni_mock()
    with patch(
        "app.services.replication.get_active",
        AsyncMock(return_value=(MagicMock(), strategy)),
    ):
        async with _make_client(_make_pool(conn)) as client:
            r = await client.post(
                "/v1/admin/replication/patroni/resume", headers=_admin_header()
            )
    assert r.status_code == 200
    assert r.json()["paused"] is False
    strategy.resume.assert_awaited_once()
