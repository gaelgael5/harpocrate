"""Repository — table scheduled_backup (LOT scheduled backups).

Aucune logique métier (validation cron, calcul next_run) ici : ces concerns
sont dans la couche service. Le repo se contente de SQL brut.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import asyncpg


# ─── Lecture ──────────────────────────────────────────────────────────────────


_SELECT_FIELDS = """
    id, name, cron_expression, remote_id, miss_threshold_minutes,
    enabled, description, next_run_at, last_run_at, last_run_status,
    last_run_error, remote_id_disconnected_at, created_at, updated_at
"""


async def list_all(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[asyncpg.Record]:
    """Liste tous les schedules, triés par nom."""
    return await conn.fetch(
        f"SELECT {_SELECT_FIELDS} FROM scheduled_backup ORDER BY LOWER(name) ASC"
    )


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    schedule_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_SELECT_FIELDS} FROM scheduled_backup WHERE id = $1",
        schedule_id,
    )


async def list_due(
    conn: asyncpg.Connection[asyncpg.Record],
    now: datetime,
    limit: int = 50,
) -> list[asyncpg.Record]:
    """Schedules `enabled` dont next_run_at <= now. Ordonnés par due-date.

    Note : pas de SELECT FOR UPDATE — la sérialisation est garantie par
    `asyncio.Lock` côté scheduler (mono-instance asuncio assumée pour ce LOT).
    Le jour où on cluster Harpocrate, ajouter un `pg_try_advisory_lock` ou
    un `SELECT FOR UPDATE SKIP LOCKED` ici.
    """
    return await conn.fetch(
        f"""
        SELECT {_SELECT_FIELDS}
        FROM scheduled_backup
        WHERE enabled AND next_run_at <= $1
        ORDER BY next_run_at ASC
        LIMIT $2
        """,
        now,
        limit,
    )


# ─── Écriture ─────────────────────────────────────────────────────────────────


async def insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    name: str,
    cron_expression: str,
    remote_id: UUID | None,
    miss_threshold_minutes: int,
    description: str | None,
    next_run_at: datetime,
    enabled: bool = True,
) -> UUID:
    """Crée un schedule. La validation de `cron_expression` et le calcul de
    `next_run_at` sont à la charge du caller (service)."""
    return await conn.fetchval(
        """
        INSERT INTO scheduled_backup (
            name, cron_expression, remote_id, miss_threshold_minutes,
            description, enabled, next_run_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        name,
        cron_expression,
        remote_id,
        miss_threshold_minutes,
        description,
        enabled,
        next_run_at,
    )


async def update(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    schedule_id: UUID,
    name: str | None = None,
    cron_expression: str | None = None,
    remote_id: UUID | None = None,
    set_remote_id: bool = False,
    miss_threshold_minutes: int | None = None,
    description: str | None = None,
    set_description: bool = False,
    enabled: bool | None = None,
    next_run_at: datetime | None = None,
) -> int:
    """Update partiel. Pour distinguer `remote_id=None` (mettre à NULL) vs
    `remote_id absent` (ne pas toucher), utiliser `set_remote_id=True`. Idem
    pour `description`. Retourne le nombre de lignes affectées."""
    fields: list[str] = []
    values: list[object] = []
    idx = 1

    def _add(field: str, value: object) -> None:
        nonlocal idx
        fields.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if name is not None:
        _add("name", name)
    if cron_expression is not None:
        _add("cron_expression", cron_expression)
    if set_remote_id:
        _add("remote_id", remote_id)
    if miss_threshold_minutes is not None:
        _add("miss_threshold_minutes", miss_threshold_minutes)
    if set_description:
        _add("description", description)
    if enabled is not None:
        _add("enabled", enabled)
    if next_run_at is not None:
        _add("next_run_at", next_run_at)

    if not fields:
        return 0

    values.append(schedule_id)
    sql = f"UPDATE scheduled_backup SET {', '.join(fields)} WHERE id = ${idx}"
    result = await conn.execute(sql, *values)
    # asyncpg retourne "UPDATE N"
    try:
        return int(result.split(" ")[1])
    except (IndexError, ValueError):
        return 0


async def mark_run(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    schedule_id: UUID,
    last_run_at: datetime,
    last_run_status: Literal["ok", "failed", "skipped"],
    last_run_error: str | None,
    next_run_at: datetime,
) -> int:
    """Met à jour les champs `last_run_*` + `next_run_at` après un tick."""
    result = await conn.execute(
        """
        UPDATE scheduled_backup
        SET last_run_at = $1,
            last_run_status = $2,
            last_run_error = $3,
            next_run_at = $4
        WHERE id = $5
        """,
        last_run_at,
        last_run_status,
        last_run_error,
        next_run_at,
        schedule_id,
    )
    try:
        return int(result.split(" ")[1])
    except (IndexError, ValueError):
        return 0


async def delete(
    conn: asyncpg.Connection[asyncpg.Record],
    schedule_id: UUID,
) -> int:
    """Hard-delete (les schedules ne portent pas de données critiques)."""
    result = await conn.execute(
        "DELETE FROM scheduled_backup WHERE id = $1", schedule_id
    )
    try:
        return int(result.split(" ")[1])
    except (IndexError, ValueError):
        return 0
