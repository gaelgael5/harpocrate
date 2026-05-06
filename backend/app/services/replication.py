"""Service réplication (LOT_20).

Pont entre :
- la table `replication_strategies` (DB),
- l'enum/abstract `ReplicationStrategy` (code),
- les endpoints admin et l'init au démarrage.

Au démarrage, on s'assure que la stratégie déclarée par
`HARPOCRATE_REPLICATION_STRATEGY` existe en DB et est active.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.core.config import settings
from app.core.logging import logger
from app.core.replication import ReplicationStrategy, build_strategy
from app.db.repositories import replication_strategies as repo


def _config_from_env() -> dict[str, Any]:
    """Construit la config par défaut pour la stratégie env-déclarée."""
    if settings.replication_strategy == "patroni":
        urls = [u.strip() for u in settings.patroni_api_urls.split(",") if u.strip()]
        return {
            "patroni_api_urls": urls,
            "replica_dsn": settings.postgres_replica_dsn or None,
        }
    return {}


def _label_for(type_: str) -> str:
    return {
        "none": "Standalone",
        "patroni": "Patroni + etcd",
        "harpocrate_sync": "Harpocrate Sync (replication applicative)",
        "s3_wal": "S3 WAL Archiving",
    }.get(type_, type_)


def _description_for(type_: str) -> str:
    return {
        "none": "Postgres standalone — aucune réplication.",
        "patroni": "Streaming replication PostgreSQL avec failover automatique via Patroni + etcd.",
        "harpocrate_sync": "Réplication applicative inter-instances (LOT 21B).",
        "s3_wal": "Archivage WAL continu vers S3-compatible (lot futur).",
    }.get(type_, "")


async def ensure_env_strategy_active(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Au démarrage : crée + active la stratégie env si pas déjà fait.

    Idempotent — si l'admin a basculé manuellement vers une autre stratégie
    via l'UI, on respecte son choix (on ne réécrase pas l'active).
    """
    requested = settings.replication_strategy
    active = await repo.get_active_strategy(conn)
    if active is not None and active["type"] == requested:
        return  # déjà aligné

    label = _label_for(requested)
    config = _config_from_env()
    new_id = await repo.upsert_strategy(
        conn,
        type_=requested,
        label=label,
        description=_description_for(requested),
        config=config,
    )
    if active is None:
        # Première initialisation : on active.
        await repo.activate_strategy(conn, new_id)
        logger.info(
            "replication_strategy_seeded_active",
            type=requested,
            strategy_id=str(new_id),
        )
    else:
        logger.info(
            "replication_strategy_env_diverges_from_active",
            env=requested,
            active=active["type"],
            note="UI choice respected",
        )


async def get_active(
    conn: asyncpg.Connection[asyncpg.Record],
) -> tuple[asyncpg.Record, ReplicationStrategy] | None:
    """Retourne (row DB, instance Strategy) ou None si aucune active."""
    row = await repo.get_active_strategy(conn)
    if row is None:
        return None
    config = row["config"] if isinstance(row["config"], dict) else {}
    strategy = build_strategy(type_=row["type"], config=config)
    return row, strategy


async def activate(
    conn: asyncpg.Connection[asyncpg.Record],
    strategy_id: UUID,
) -> bool:
    """Bascule la stratégie active. Retourne False si l'ID est inconnu/désactivé."""
    return await repo.activate_strategy(conn, strategy_id)


def row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Sérialise une row pour JSONResponse."""
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "label": row["label"],
        "description": row["description"],
        "config": row["config"] if isinstance(row["config"], dict) else {},
        "enabled": row["enabled"],
        "is_active": row["is_active"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
