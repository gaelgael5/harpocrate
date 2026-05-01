"""Schémas Pydantic pour les endpoints /v1/audit-log/* — LOT_10."""
from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ─── Item de réponse ──────────────────────────────────────────────────────────


class ActorInfo(BaseModel):
    """Informations sur l'acteur (user ou api_key)."""

    type: str  # "user" | "api_key"
    id: UUID | None
    email: str | None = None
    display_name: str | None = None
    name: str | None = None  # pour api_key : api_key.name


class TargetInfo(BaseModel):
    """Informations sur la cible de l'action."""

    wallet_id: UUID | None = None
    wallet_name: str | None = None
    secret_id: UUID | None = None
    user_id: UUID | None = None
    api_key_id: UUID | None = None


class AuditLogItem(BaseModel):
    """Un événement d'audit log retourné par l'API."""

    id: int
    occurred_at: datetime.datetime
    action: str
    actor: ActorInfo
    target: TargetInfo
    metadata: dict[str, object] | None
    success: bool
    error_code: str | None
    actor_ip: str | None


# ─── Réponse liste ────────────────────────────────────────────────────────────


class AuditLogResponse(BaseModel):
    """Réponse de GET /v1/audit-log."""

    events: list[AuditLogItem]
    next_cursor: str | None


class AuditLogActionsResponse(BaseModel):
    """Réponse de GET /v1/audit-log/actions."""

    actions: list[str]


# ─── Paramètres de requête (validés manuellement dans l'endpoint) ─────────────


class AuditLogFilters(BaseModel):
    """Filtres optionnels pour GET /v1/audit-log."""

    wallet_id: UUID | None = None
    action: str | None = None
    action_prefix: str | None = None
    since: datetime.datetime | None = None
    until: datetime.datetime | None = None
    actor_user_id: UUID | None = None
    actor_api_key_id: UUID | None = None
    target_secret_id: UUID | None = None
    success: bool | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
