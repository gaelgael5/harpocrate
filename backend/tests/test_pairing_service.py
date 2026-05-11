"""Tests service pairing — init_master + génération de code (LOT 2)."""

from __future__ import annotations

import json

import asyncpg

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
