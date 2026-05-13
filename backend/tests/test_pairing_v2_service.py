"""Tests service pairing v2 (LOT 5 — échange d'URL signée)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from app.services import pairing as svc_v1
from app.services import pairing_v2 as svc
from app.services.pairing_url_codec import (
    InvalidPairingUrlError,
    build_pairing_url,
)


async def test_init_master_v2_returns_pairing_url(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        result = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            assert result.session_id is not None
            assert result.expires_in_seconds > 0
            assert "/pair?sid=" in result.pairing_url
            assert "&t=" in result.pairing_url
        finally:
            await conn.execute(
                "DELETE FROM pairing_session WHERE id = $1",
                result.session_id,
            )
            await conn.execute(
                "DELETE FROM audit_log WHERE action = 'pairing.master_init_v2' "
                "AND created_at >= now() - interval '1 minute'"
            )


async def test_init_master_v2_rejects_invalid_standby_url(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.PairingAcceptError):
            await svc.init_master_v2(
                conn,
                standby_url="not-an-url",
                actor_user_id=None,
            )
        with pytest.raises(svc_v1.PairingAcceptError):
            await svc.init_master_v2(
                conn,
                standby_url="",
                actor_user_id=None,
            )


async def test_confirm_master_v2_invalid_session_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    from uuid import uuid4

    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.confirm_master_v2(
                conn,
                session_id=uuid4(),
                token="a" * 32,
                standby_url="https://b/",
                actor_user_id=None,
            )


async def test_confirm_master_v2_token_mismatch_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        init = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            with pytest.raises(svc_v1.InvalidCodeError):
                await svc.confirm_master_v2(
                    conn,
                    session_id=init.session_id,
                    token="0" * 32,
                    standby_url="https://b.example/",
                    actor_user_id=None,
                )
        finally:
            await conn.execute(
                "DELETE FROM pairing_session WHERE id = $1",
                init.session_id,
            )
            await conn.execute(
                "DELETE FROM audit_log WHERE action IN "
                "('pairing.master_init_v2', 'pairing.failed') "
                "AND created_at >= now() - interval '1 minute'"
            )


async def test_accept_standby_v2_invalid_url_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(InvalidPairingUrlError):
            await svc.accept_standby_v2(
                conn,
                pairing_url="https://master/wrong-path?foo=bar",
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_v2_network_error_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Master injoignable → PairingAcceptError."""
    from uuid import uuid4

    url = build_pairing_url("https://does-not-exist.invalid", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.PairingAcceptError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_v2_invalid_token_raises_invalid_code(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """403 du master → InvalidCodeError."""
    from uuid import uuid4

    fake_resp = MagicMock()
    fake_resp.status_code = 403

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.post = AsyncMock(return_value=fake_resp)

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_v2_verify_tls_default_strict(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Par défaut, httpx.AsyncClient est instancié avec verify=True."""
    from uuid import uuid4

    captured: dict[str, object] = {}

    def fake_async_client(*args: object, **kwargs: object) -> AsyncMock:
        captured.update(kwargs)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        resp = MagicMock()
        resp.status_code = 403
        client.post = AsyncMock(return_value=resp)
        return client

    monkeypatch.setattr(svc.httpx, "AsyncClient", fake_async_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )
    assert captured.get("verify") is True


async def test_accept_standby_v2_verify_tls_disabled_when_setting_true(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Quand allow_self_signed=True, verify=False et un warning est loggé."""
    from uuid import uuid4

    from app.core.config import settings

    monkeypatch.setattr(settings, "replication_pairing_allow_self_signed", True)

    captured: dict[str, object] = {}

    def fake_async_client(*args: object, **kwargs: object) -> AsyncMock:
        captured.update(kwargs)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        resp = MagicMock()
        resp.status_code = 403
        client.post = AsyncMock(return_value=resp)
        return client

    monkeypatch.setattr(svc.httpx, "AsyncClient", fake_async_client)

    warnings: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        svc.logger,
        "warning",
        lambda event, **kw: warnings.append((event, kw)),
    )

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )
    assert captured.get("verify") is False
    assert any(ev == "pairing_v2.tls_verification_disabled" for ev, _ in warnings)
