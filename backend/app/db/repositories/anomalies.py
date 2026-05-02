"""Repository pour identity_anomaly_events (LOT_02 governance)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.identity import AnomalyEventRow


def _row_to_model(row: asyncpg.Record) -> AnomalyEventRow:
    raw = dict(row)
    meta = raw.get("metadata")
    if isinstance(meta, str):
        raw["metadata"] = json.loads(meta)
    return AnomalyEventRow(**raw)


async def insert(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    severity: str,
    anomaly_type: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    new_id: int = await conn.fetchval(
        """
        INSERT INTO identity_anomaly_events (
            user_id, severity, anomaly_type, metadata
        ) VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id
        """,
        user_id,
        severity,
        anomaly_type,
        json.dumps(metadata) if metadata else None,
    )
    return new_id


async def list_by_user(
    conn: asyncpg.Connection,
    user_id: UUID,
    *,
    only_unacknowledged: bool = False,
    limit: int = 100,
) -> list[AnomalyEventRow]:
    if only_unacknowledged:
        rows = await conn.fetch(
            "SELECT * FROM identity_anomaly_events "
            "WHERE user_id = $1 AND acknowledged_at IS NULL "
            "ORDER BY detected_at DESC LIMIT $2",
            user_id,
            limit,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM identity_anomaly_events "
            "WHERE user_id = $1 "
            "ORDER BY detected_at DESC LIMIT $2",
            user_id,
            limit,
        )
    return [_row_to_model(r) for r in rows]


async def acknowledge(
    conn: asyncpg.Connection,
    anomaly_id: int,
    user_id: UUID,
    by_user_id: UUID,
) -> bool:
    """Marque l'anomalie comme acquittee. Retourne False si pas trouvee ou pas
    a l'utilisateur."""
    result = await conn.execute(
        """
        UPDATE identity_anomaly_events
        SET acknowledged_at = NOW(), acknowledged_by_user_id = $3
        WHERE id = $1 AND user_id = $2 AND acknowledged_at IS NULL
        """,
        anomaly_id,
        user_id,
        by_user_id,
    )
    return str(result) != "UPDATE 0"
