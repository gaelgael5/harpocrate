"""Tests service pairing — init_master + génération de code (LOT 2)."""

from __future__ import annotations

import json

import asyncpg
import pytest

from app.services import pairing as svc


async def test_init_master_returns_4digit_code(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        result = await svc.init_master(
            conn,
            partner_url="https://b.example/",
            actor_user_id=None,
        )
        # cleanup
        await conn.execute(
            "DELETE FROM pairing_session WHERE id = $1",
            result.session_id,
        )
    assert len(result.code) == 4
    assert result.code.isdigit()
    assert result.session_id is not None
    assert result.expires_in_seconds > 0


async def test_init_master_generates_distinct_codes(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Sur 10 inits successifs on attend au moins 8 codes distincts.

    Collision possible (10000 valeurs) mais très rare sur 10 tirages.
    """
    async with real_db_pool.acquire() as conn:
        sids = []
        codes = set()
        try:
            for _ in range(10):
                r = await svc.init_master(
                    conn,
                    partner_url="https://b/",
                    actor_user_id=None,
                )
                sids.append(r.session_id)
                codes.add(r.code)
        finally:
            for sid in sids:
                await conn.execute(
                    "DELETE FROM pairing_session WHERE id = $1",
                    sid,
                )
    assert len(codes) >= 8


async def test_init_master_audit_event_written(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Vérifie que l'event pairing.master_init apparait dans audit_log."""
    async with real_db_pool.acquire() as conn:
        result = await svc.init_master(
            conn,
            partner_url="https://b.example/",
            actor_user_id=None,
        )
        # Récupère le dernier event audit_log de type pairing.master_init
        row = await conn.fetchrow(
            "SELECT action, metadata FROM audit_log "
            "WHERE action = 'pairing.master_init' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        # cleanup
        await conn.execute(
            "DELETE FROM audit_log WHERE action = 'pairing.master_init' "
            "AND created_at >= now() - interval '1 minute'"
        )
        await conn.execute(
            "DELETE FROM pairing_session WHERE id = $1",
            result.session_id,
        )
    assert row is not None
    assert row["action"] == "pairing.master_init"
    # metadata est JSONB, peut être renvoyé comme str selon asyncpg
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta["partner_url"] == "https://b.example/"
    assert meta["code_prefix"].endswith("**")


def test_generate_code_is_4_digits() -> None:
    """Pure unit test — pas de DB."""
    for _ in range(100):
        c = svc._generate_code()
        assert len(c) == 4
        assert c.isdigit()


# ─── Tests Task 2.3 — confirm_master + accept_standby ────────────────────────


async def test_confirm_master_with_invalid_code_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc.InvalidCodeError):
            await svc.confirm_master(
                conn,
                code="0000",
                standby_url="https://b/",
                actor_user_id=None,
            )


async def test_confirm_master_rate_limits_after_max_attempts(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Après pairing_max_attempts tentatives, le code valide est refusé."""
    from app.core.config import settings
    from app.db.repositories import pairing_sessions as repo

    async with real_db_pool.acquire() as conn:
        result = await svc.init_master(
            conn,
            partner_url="https://b/",
            actor_user_id=None,
        )
        try:
            for _ in range(settings.pairing_max_attempts):
                await repo.increment_attempts(conn, result.session_id)
            with pytest.raises(svc.TooManyAttemptsError):
                await svc.confirm_master(
                    conn,
                    code=result.code,
                    standby_url="https://b/",
                    actor_user_id=None,
                )
        finally:
            await conn.execute(
                "DELETE FROM pairing_session WHERE id = $1",
                result.session_id,
            )
            await conn.execute(
                "DELETE FROM audit_log WHERE action IN "
                "('pairing.master_init', 'pairing.failed') "
                "AND created_at >= now() - interval '1 minute'"
            )


async def test_accept_standby_network_error_raises_pairing_accept_error(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si A est injoignable (DNS error, timeout), PairingAcceptError est levée."""
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc.PairingAcceptError):
            await svc.accept_standby(
                conn,
                master_url="https://does-not-exist.invalid",
                code="1234",
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_invalid_code_raises_invalid_code_error(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """403 de A → InvalidCodeError."""
    from unittest.mock import AsyncMock, MagicMock

    fake_resp = MagicMock()
    fake_resp.status_code = 403

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.post = AsyncMock(return_value=fake_resp)

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc.InvalidCodeError):
            await svc.accept_standby(
                conn,
                master_url="https://a/",
                code="0000",
                self_url="https://b/",
                actor_user_id=None,
            )


# ─── Tests unitaires _host_from_url ──────────────────────────────────────────


def test_host_from_url_extracts_hostname() -> None:
    assert svc._host_from_url("https://b.example/") == "b.example"


def test_host_from_url_with_port() -> None:
    assert svc._host_from_url("https://b.example:5443/") == "b.example"


def test_host_from_url_with_no_schema() -> None:
    """urlparse sans schéma ne trouve pas de hostname → raise."""
    with pytest.raises(svc.PairingAcceptError):
        svc._host_from_url("b.example")


def test_host_from_url_with_empty_string() -> None:
    with pytest.raises(svc.PairingAcceptError):
        svc._host_from_url("")
