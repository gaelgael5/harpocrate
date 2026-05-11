"""Migration 028 — vérifie que la table pairing_session est créée correctement."""

from __future__ import annotations

import asyncpg

_EXPECTED_COLUMNS = [
    "id",
    "role",
    "code",
    "partner_url",
    "status",
    "payload",
    "current_step_idx",
    "created_at",
    "expires_at",
    "attempts",
    "actor_user_id",
]


async def test_pairing_session_table_exists(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'pairing_session' "
            "ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for expected in _EXPECTED_COLUMNS:
        assert expected in names, f"colonne manquante : {expected}"
