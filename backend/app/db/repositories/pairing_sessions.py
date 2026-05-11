"""CRUD pairing_session — sessions d'appairage entre 2 instances Harpocrate."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import asyncpg

PairingRole = Literal["master", "standby"]
PairingStatus = Literal[
    "pending",
    "confirmed",
    "wizard",
    "completed",
    "expired",
    "failed",
]

_SELECT_FIELDS = (
    "id, role, code, partner_url, status, payload, current_step_idx, "
    "attempts, actor_user_id, created_at, expires_at"
)


async def create(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    role: PairingRole,
    code: str,
    partner_url: str | None,
    ttl_seconds: int,
    actor_user_id: UUID | None,
) -> UUID:
    expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return await conn.fetchval(
        """
        INSERT INTO pairing_session (role, code, partner_url, expires_at, actor_user_id)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
        """,
        role,
        code,
        partner_url,
        expires,
        actor_user_id,
    )


async def get(conn: asyncpg.Connection[asyncpg.Record], sid: UUID) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        f"SELECT {_SELECT_FIELDS} FROM pairing_session WHERE id = $1",
        sid,
    )
    if row is None:
        return None
    out = dict(row)
    if isinstance(out["payload"], str):
        out["payload"] = json.loads(out["payload"])
    return out


async def get_active_by_code(
    conn: asyncpg.Connection[asyncpg.Record], code: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        f"SELECT {_SELECT_FIELDS} FROM pairing_session "
        "WHERE code = $1 AND status IN ('pending', 'confirmed') "
        "AND expires_at > now() ORDER BY created_at DESC LIMIT 1",
        code,
    )
    if row is None:
        return None
    out = dict(row)
    if isinstance(out["payload"], str):
        out["payload"] = json.loads(out["payload"])
    return out


async def increment_attempts(
    conn: asyncpg.Connection[asyncpg.Record],
    sid: UUID,
) -> int | None:
    """Retourne le nouveau compteur d'essais, ou None si la session n'existe pas."""
    return await conn.fetchval(
        "UPDATE pairing_session SET attempts = attempts + 1 WHERE id = $1 RETURNING attempts",
        sid,
    )


async def set_status(
    conn: asyncpg.Connection[asyncpg.Record], sid: UUID, status: PairingStatus
) -> None:
    await conn.execute(
        "UPDATE pairing_session SET status = $1 WHERE id = $2",
        status,
        sid,
    )


async def set_payload(
    conn: asyncpg.Connection[asyncpg.Record],
    sid: UUID,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        "UPDATE pairing_session SET payload = $1::jsonb WHERE id = $2",
        json.dumps(payload),
        sid,
    )


async def set_step_idx(conn: asyncpg.Connection[asyncpg.Record], sid: UUID, idx: int) -> None:
    await conn.execute(
        "UPDATE pairing_session SET current_step_idx = $1 WHERE id = $2",
        idx,
        sid,
    )


async def expire_old(conn: asyncpg.Connection[asyncpg.Record]) -> int:
    res = await conn.execute(
        "UPDATE pairing_session SET status = 'expired' "
        "WHERE status IN ('pending','confirmed','wizard') AND expires_at < now()"
    )
    if not res:
        return 0
    try:
        return int(res.split()[-1])
    except (ValueError, IndexError):
        return 0
