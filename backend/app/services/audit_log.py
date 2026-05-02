"""Service audit_log — logique métier de LECTURE des événements d'audit (LOT_10).

Ne pas confondre avec app/services/audit.py qui est le helper d'ÉCRITURE.
"""
from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.db.repositories import audit_log as audit_log_repo
from app.models.api.audit_log import (
    ActorInfo,
    AuditLogFilters,
    AuditLogItem,
    AuditLogResponse,
    TargetInfo,
)

# ─── Conversion row → AuditLogItem ───────────────────────────────────────────


def _row_to_item(row: asyncpg.Record) -> AuditLogItem:
    """Convertit une ligne DB en AuditLogItem, en filtrant les metadata sensibles."""
    raw_metadata: dict[str, Any] | None = None
    raw = row["metadata"]
    if raw is not None:
        # asyncpg retourne JSONB en string par defaut (pas de codec installe).
        # Si on a deja installe un codec ailleurs, ce sera un dict directement.
        if isinstance(raw, str):
            import json
            raw_metadata = json.loads(raw)
        elif isinstance(raw, dict):
            raw_metadata = dict(raw)

    cleaned_metadata = audit_log_repo.strip_sensitive_metadata(raw_metadata)

    if row["actor_api_key_id"] is not None:
        actor = ActorInfo(
            type="api_key",
            id=row["actor_api_key_id"],
            name=row["actor_api_key_name"],
        )
    else:
        actor = ActorInfo(
            type="user",
            id=row["actor_user_id"],
            email=row["actor_user_email"],
            display_name=row["actor_user_display_name"],
        )

    target = TargetInfo(
        wallet_id=row["target_wallet_id"],
        wallet_name=row["target_wallet_name"],
        secret_id=row["target_secret_id"],
        user_id=row["target_user_id"],
        api_key_id=row["target_api_key_id"],
    )

    actor_ip: str | None = row["actor_ip"]

    return AuditLogItem(
        id=row["id"],
        occurred_at=row["occurred_at"],
        action=row["action"],
        actor=actor,
        target=target,
        metadata=cleaned_metadata,
        success=row["success"],
        error_code=row["error_code"],
        actor_ip=actor_ip,
    )


# ─── Service principal ────────────────────────────────────────────────────────


async def query_audit_log_for_jwt(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
    filters: AuditLogFilters,
) -> AuditLogResponse:
    """Requête audit_log pour un caller JWT.

    Visibilité : ses propres actions OU actions sur ses wallets owned.
    Les filtres optionnels sont appliqués en plus.
    """
    cursor_occurred_at: datetime.datetime | None = None
    cursor_id: int | None = None

    if filters.cursor:
        try:
            cursor_occurred_at, cursor_id = audit_log_repo.decode_cursor(
                filters.cursor
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_cursor", "message": str(exc)},
            ) from exc

    owned_wallet_ids = await audit_log_repo.get_owned_wallet_ids(conn, user_id)

    rows = await audit_log_repo.query_audit_log(
        conn,
        jwt_user_id=user_id,
        jwt_owned_wallet_ids=owned_wallet_ids,
        filter_wallet_id=filters.wallet_id,
        filter_action=filters.action,
        filter_action_prefix=filters.action_prefix,
        filter_since=filters.since,
        filter_until=filters.until,
        filter_actor_user_id=filters.actor_user_id,
        filter_actor_api_key_id=filters.actor_api_key_id,
        filter_target_secret_id=filters.target_secret_id,
        filter_success=filters.success,
        cursor_occurred_at=cursor_occurred_at,
        cursor_id=cursor_id,
        limit=filters.limit,
    )

    return _build_response(rows, filters.limit)


async def query_audit_log_for_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    api_key_id: UUID,
    filters: AuditLogFilters,
) -> AuditLogResponse:
    """Requête audit_log pour un caller API key.

    Filtre forcé : uniquement les actions de cet api_key_id.
    Tous les filtres utilisateur (wallet_id, actor_user_id, etc.) sont ignorés.
    """
    cursor_occurred_at: datetime.datetime | None = None
    cursor_id: int | None = None

    if filters.cursor:
        try:
            cursor_occurred_at, cursor_id = audit_log_repo.decode_cursor(
                filters.cursor
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_cursor", "message": str(exc)},
            ) from exc

    rows = await audit_log_repo.query_audit_log(
        conn,
        force_actor_api_key_id=api_key_id,
        # Filtres communs autorisés pour API key
        filter_action=filters.action,
        filter_action_prefix=filters.action_prefix,
        filter_since=filters.since,
        filter_until=filters.until,
        filter_success=filters.success,
        cursor_occurred_at=cursor_occurred_at,
        cursor_id=cursor_id,
        limit=filters.limit,
    )

    return _build_response(rows, filters.limit)


# ─── Helper réponse paginée ───────────────────────────────────────────────────


def _build_response(
    rows: list[asyncpg.Record],
    limit: int,
) -> AuditLogResponse:
    """Construit AuditLogResponse à partir des rows DB (+1 trick pour next_cursor)."""
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = [_row_to_item(row) for row in page_rows]

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = audit_log_repo.encode_cursor(last["occurred_at"], last["id"])

    return AuditLogResponse(events=items, next_cursor=next_cursor)
