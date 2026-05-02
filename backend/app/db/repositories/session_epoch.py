"""Repository pour server_session_epoch (LOT_02 governance).

Singleton (id=1) qui contient le numero d'epoch courant. Bump apres un restore
de backup pour invalider tous les JWT emis avant le restore.
"""
from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

import asyncpg


class SessionEpoch(NamedTuple):
    epoch: int
    rotated_at: datetime
    rotated_reason: str | None


async def get(conn: asyncpg.Connection) -> SessionEpoch:
    row = await conn.fetchrow(
        "SELECT epoch, rotated_at, rotated_reason FROM server_session_epoch WHERE id = 1"
    )
    if row is None:
        raise RuntimeError(
            "server_session_epoch not initialized — la migration 002 doit avoir tourne"
        )
    return SessionEpoch(
        epoch=row["epoch"],
        rotated_at=row["rotated_at"],
        rotated_reason=row["rotated_reason"],
    )


async def bump(conn: asyncpg.Connection, reason: str) -> int:
    """Incremente l'epoch (a faire apres un restore de backup).
    Retourne le nouvel epoch."""
    new_epoch: int = await conn.fetchval(
        """
        UPDATE server_session_epoch
        SET epoch = epoch + 1,
            rotated_at = NOW(),
            rotated_reason = $1
        WHERE id = 1
        RETURNING epoch
        """,
        reason,
    )
    return new_epoch
