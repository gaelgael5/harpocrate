"""Dataclass pour user_external_identities (LOT_02)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class ExternalIdentityRow:
    """Une ligne user_external_identities."""

    id: UUID
    user_id: UUID
    provider: str
    external_subject: str
    is_primary: bool
    linked_at: datetime
    last_login_at: datetime | None
    linked_email: str | None
    linked_display_name: str | None


@dataclass
class AnomalyEventRow:
    """Une ligne identity_anomaly_events."""

    id: int
    user_id: UUID
    detected_at: datetime
    severity: str
    anomaly_type: str
    metadata: dict[str, object] | str | None
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None


@dataclass
class ReverifyTokenRow:
    """Une ligne reverify_tokens."""

    id: UUID
    user_id: UUID
    token_hash: bytes
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
