"""Repository — table notification_events (LOT_57)."""
from __future__ import annotations

import datetime
import json
from typing import Any

import asyncpg


async def insert_event(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    transaction_id: str,
    event_type: str,
    occurred_at: datetime.datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Persiste un nouvel event de notification. Retourne l'ID auto-généré.

    `event_type` doit être dans l'enum (`sent`, `delivery`, `open`, `click`,
    `failed`) — le CHECK SQL valide. Lever IntegrityError si invalide.
    """
    return await conn.fetchval(
        """
        INSERT INTO notification_events
            (transaction_id, event_type, occurred_at, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id
        """,
        transaction_id,
        event_type,
        occurred_at,
        json.dumps(metadata) if metadata is not None else None,
    )


async def list_events_for_transaction(
    conn: asyncpg.Connection[asyncpg.Record],
    transaction_id: str,
) -> list[asyncpg.Record]:
    """Retourne l'historique complet (du plus ancien au plus récent)."""
    return await conn.fetch(
        """
        SELECT id, transaction_id, event_type, received_at, occurred_at, metadata
        FROM notification_events
        WHERE transaction_id = $1
        ORDER BY received_at ASC
        """,
        transaction_id,
    )


async def get_latest_event(
    conn: asyncpg.Connection[asyncpg.Record],
    transaction_id: str,
) -> asyncpg.Record | None:
    """Retourne l'event le plus récent pour cette transaction, ou None."""
    return await conn.fetchrow(
        """
        SELECT id, transaction_id, event_type, received_at, occurred_at, metadata
        FROM notification_events
        WHERE transaction_id = $1
        ORDER BY received_at DESC
        LIMIT 1
        """,
        transaction_id,
    )


async def list_latest_events_for_transactions(
    conn: asyncpg.Connection[asyncpg.Record],
    transaction_ids: list[str],
) -> dict[str, asyncpg.Record]:
    """Pour un batch de transaction_ids, retourne le mapping
    `{transaction_id: latest_event_record}`. Optimise l'affichage admin
    (évite N+1 queries quand on liste les recovery_sessions)."""
    if not transaction_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (transaction_id)
            transaction_id, event_type, received_at, occurred_at, metadata
        FROM notification_events
        WHERE transaction_id = ANY($1::text[])
        ORDER BY transaction_id, received_at DESC
        """,
        transaction_ids,
    )
    return {r["transaction_id"]: r for r in rows}
