"""Service système pour reporter et lister les anomalies d'infrastructure.

Pourquoi un service distinct du repo : c'est l'API que les autres modules
utilisent pour reporter une anomalie (snapshot push, replication, etc.). Ça
évite que chaque module aille toucher la table en SQL et garantit qu'on
log + valide la severity de manière uniforme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import asyncpg
import structlog

from app.db.repositories import system_anomalies as repo


logger = structlog.get_logger(__name__)


Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class SystemAnomaly:
    id: int
    detected_at: str
    severity: str
    anomaly_type: str
    source: str
    source_ref_id: UUID | None
    message: str
    metadata: dict[str, Any] | None
    acknowledged_at: str | None
    acknowledged_by_user_id: UUID | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "detected_at": self.detected_at,
            "severity": self.severity,
            "anomaly_type": self.anomaly_type,
            "source": self.source,
            "source_ref_id": str(self.source_ref_id) if self.source_ref_id else None,
            "message": self.message,
            "metadata": self.metadata,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by_user_id": (
                str(self.acknowledged_by_user_id) if self.acknowledged_by_user_id else None
            ),
        }


def _row_to_dto(row: asyncpg.Record) -> SystemAnomaly:
    import json

    raw_meta = row["metadata"]
    if isinstance(raw_meta, str):
        meta = json.loads(raw_meta)
    elif raw_meta is None:
        meta = None
    else:
        meta = dict(raw_meta)

    return SystemAnomaly(
        id=row["id"],
        detected_at=row["detected_at"].isoformat(),
        severity=row["severity"],
        anomaly_type=row["anomaly_type"],
        source=row["source"],
        source_ref_id=row["source_ref_id"],
        message=row["message"],
        metadata=meta,
        acknowledged_at=(
            row["acknowledged_at"].isoformat() if row["acknowledged_at"] else None
        ),
        acknowledged_by_user_id=row["acknowledged_by_user_id"],
    )


async def report(
    conn: asyncpg.Connection,
    *,
    severity: Severity,
    anomaly_type: str,
    source: str,
    message: str,
    source_ref_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Crée une anomalie système. Loggue aussi (warning/error selon severity)
    pour qu'elle soit visible dans Loki/Grafana en parallèle de l'UI.
    """
    new_id = await repo.insert(
        conn,
        severity=severity,
        anomaly_type=anomaly_type,
        source=source,
        source_ref_id=source_ref_id,
        message=message,
        metadata=metadata,
    )
    log_method = logger.error if severity == "critical" else logger.warning
    log_method(
        "system_anomaly_reported",
        anomaly_id=new_id,
        severity=severity,
        anomaly_type=anomaly_type,
        source=source,
        source_ref_id=str(source_ref_id) if source_ref_id else None,
        message=message,
    )
    return new_id


async def list_anomalies(
    conn: asyncpg.Connection,
    *,
    only_unacknowledged: bool = False,
    limit: int = 200,
) -> list[SystemAnomaly]:
    rows = await repo.list_all(
        conn, only_unacknowledged=only_unacknowledged, limit=limit
    )
    return [_row_to_dto(r) for r in rows]


async def acknowledge_anomaly(
    conn: asyncpg.Connection,
    anomaly_id: int,
    by_user_id: UUID | None,
) -> bool:
    return await repo.acknowledge(conn, anomaly_id, by_user_id)
