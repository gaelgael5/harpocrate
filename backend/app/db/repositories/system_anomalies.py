"""Repository — table system_anomaly_events (anomalies d'infrastructure)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg


_SELECT_FIELDS = """
    id, detected_at, severity, anomaly_type, source, source_ref_id,
    message, metadata, acknowledged_at, acknowledged_by_user_id
"""


async def insert(
    conn: asyncpg.Connection,
    *,
    severity: str,
    anomaly_type: str,
    source: str,
    source_ref_id: UUID | None,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO system_anomaly_events (
            severity, anomaly_type, source, source_ref_id, message, metadata
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        RETURNING id
        """,
        severity,
        anomaly_type,
        source,
        source_ref_id,
        message,
        json.dumps(metadata) if metadata else None,
    )


async def list_all(
    conn: asyncpg.Connection,
    *,
    only_unacknowledged: bool = False,
    limit: int = 200,
) -> list[asyncpg.Record]:
    if only_unacknowledged:
        return await conn.fetch(
            f"""
            SELECT {_SELECT_FIELDS}
            FROM system_anomaly_events
            WHERE acknowledged_at IS NULL
            ORDER BY detected_at DESC
            LIMIT $1
            """,
            limit,
        )
    return await conn.fetch(
        f"""
        SELECT {_SELECT_FIELDS}
        FROM system_anomaly_events
        ORDER BY detected_at DESC
        LIMIT $1
        """,
        limit,
    )


async def acknowledge(
    conn: asyncpg.Connection,
    anomaly_id: int,
    by_user_id: UUID | None,
) -> bool:
    """Marque une anomalie comme acquittée. Retourne False si déjà ack ou
    introuvable. `by_user_id` peut être NULL (ex: ack via local-admin sans
    row users — peu probable mais on tolère)."""
    result = await conn.execute(
        """
        UPDATE system_anomaly_events
        SET acknowledged_at = NOW(), acknowledged_by_user_id = $2
        WHERE id = $1 AND acknowledged_at IS NULL
        """,
        anomaly_id,
        by_user_id,
    )
    return str(result) != "UPDATE 0"
