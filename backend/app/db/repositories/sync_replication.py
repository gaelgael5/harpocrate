"""Repository — tables sync_log, sync_shelf, sync_replication_state (LOT_21B)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

# ─── sync_log ────────────────────────────────────────────────────────────────


async def fetch_outbound_batch(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    emitter_id: str,
    cursor: int,
    limit: int = 100,
) -> list[asyncpg.Record]:
    """Récupère le prochain batch à publier (entries propres > cursor)."""
    return await conn.fetch(
        """
        SELECT seq, type, entity_type, entity_id, operation,
               payload, source_emitter, source_seq, occurred_at
        FROM sync_log
        WHERE emitter_id = $1 AND seq > $2
        ORDER BY seq ASC
        LIMIT $3
        """,
        emitter_id,
        cursor,
        limit,
    )


async def get_push_cursor(
    conn: asyncpg.Connection[asyncpg.Record],
) -> int:
    raw = await conn.fetchval(
        "SELECT value::text FROM system_metadata WHERE key = 'sync_push_cursor'"
    )
    if raw is None:
        return 0
    try:
        return int(json.loads(raw)) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        return 0


async def set_push_cursor(
    conn: asyncpg.Connection[asyncpg.Record],
    cursor: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO system_metadata (key, value, updated_at)
        VALUES ('sync_push_cursor', $1::jsonb, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        json.dumps(cursor),
    )


async def insert_replication_ack(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    emitter_id: str,
    source_emitter: str,
    source_seq: int,
) -> int:
    """Insère un ack vide dans sync_log et retourne son seq."""
    return await conn.fetchval(
        """
        INSERT INTO sync_log (emitter_id, type, source_emitter, source_seq, is_replication)
        VALUES ($1, 'replication_ack', $2, $3, TRUE)
        RETURNING seq
        """,
        emitter_id,
        source_emitter,
        source_seq,
    )


# ─── sync_shelf ──────────────────────────────────────────────────────────────


async def shelve_message(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    source_emitter: str,
    source_seq: int,
    payload: dict[str, Any],
) -> None:
    """Stocke un message reçu hors-ordre (gap dans la séquence)."""
    await conn.execute(
        """
        INSERT INTO sync_shelf (source_emitter, source_seq, payload)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (source_emitter, source_seq) DO NOTHING
        """,
        source_emitter,
        source_seq,
        json.dumps(payload),
    )


async def fetch_next_shelved(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    source_emitter: str,
    expected_seq: int,
) -> asyncpg.Record | None:
    """Retourne le message à expected_seq depuis l'étagère, ou None."""
    return await conn.fetchrow(
        """
        SELECT payload FROM sync_shelf
        WHERE source_emitter = $1 AND source_seq = $2
        """,
        source_emitter,
        expected_seq,
    )


async def remove_shelved(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    source_emitter: str,
    source_seq: int,
) -> None:
    await conn.execute(
        "DELETE FROM sync_shelf WHERE source_emitter = $1 AND source_seq = $2",
        source_emitter,
        source_seq,
    )


# ─── sync_replication_state ──────────────────────────────────────────────────


async def get_state_for_peer(
    conn: asyncpg.Connection[asyncpg.Record],
    peer: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT peer_emitter, last_applied_seq, last_acked_seq, last_received_seq,
               last_seen_at, status
        FROM sync_replication_state
        WHERE peer_emitter = $1
        """,
        peer,
    )


async def list_states(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT peer_emitter, last_applied_seq, last_acked_seq, last_received_seq,
               last_seen_at, status
        FROM sync_replication_state
        ORDER BY peer_emitter
        """
    )


async def upsert_received(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    peer: str,
    last_received_seq: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO sync_replication_state
            (peer_emitter, last_received_seq, last_seen_at, status)
        VALUES ($1, $2, NOW(), 'unknown')
        ON CONFLICT (peer_emitter) DO UPDATE SET
            last_received_seq = GREATEST(sync_replication_state.last_received_seq, $2),
            last_seen_at = NOW()
        """,
        peer,
        last_received_seq,
    )


async def upsert_applied(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    peer: str,
    last_applied_seq: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO sync_replication_state
            (peer_emitter, last_applied_seq, last_received_seq, last_seen_at, status)
        VALUES ($1, $2, $2, NOW(), 'synced')
        ON CONFLICT (peer_emitter) DO UPDATE SET
            last_applied_seq = GREATEST(sync_replication_state.last_applied_seq, $2),
            last_received_seq = GREATEST(sync_replication_state.last_received_seq, $2),
            last_seen_at = NOW(),
            status = 'synced'
        """,
        peer,
        last_applied_seq,
    )
