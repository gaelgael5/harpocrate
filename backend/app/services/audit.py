"""Service audit — insère des lignes dans audit_log."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg


async def audit_log_insert(
    conn: asyncpg.Connection[asyncpg.Record],
    action: str,
    *,
    actor_user_id: UUID | None = None,
    actor_api_key_id: UUID | None = None,
    actor_ip: str | None = None,
    target_wallet_id: UUID | None = None,
    target_secret_id: UUID | None = None,
    target_user_id: UUID | None = None,
    target_api_key_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    success: bool = True,
    error_code: str | None = None,
) -> None:
    """Insère une ligne dans audit_log.

    Règle critique : metadata ne doit JAMAIS contenir de blobs cryptographiques.
    """
    metadata_json: str | None = json.dumps(metadata) if metadata else None
    await conn.execute(
        """
        INSERT INTO audit_log (
            action,
            actor_user_id, actor_api_key_id, actor_ip,
            target_wallet_id, target_secret_id, target_user_id, target_api_key_id,
            metadata, success, error_code
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        action,
        actor_user_id,
        actor_api_key_id,
        actor_ip,
        target_wallet_id,
        target_secret_id,
        target_user_id,
        target_api_key_id,
        metadata_json,
        success,
        error_code,
    )
