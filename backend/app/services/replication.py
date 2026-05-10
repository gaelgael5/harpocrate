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
        "streaming_async": "Streaming async",
    }.get(type_, type_)


def _description_for(type_: str) -> str:
    return {
        "none": "Postgres standalone — aucune réplication.",
        "patroni": "Streaming replication PostgreSQL avec failover automatique via Patroni + etcd.",
        "harpocrate_sync": "Réplication applicative inter-instances (LOT 21B).",
        "s3_wal": "Archivage WAL continu vers S3-compatible (lot futur).",
        "streaming_async": "Réplication PostgreSQL streaming asynchrone — un ou plusieurs standby. Hors-app : commandes générées par l'UI à exécuter en SSH.",
    }.get(type_, "")


async def ensure_env_strategy_active(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Au démarrage : crée la stratégie env si elle n'existe pas, l'active si
    aucune stratégie n'est encore active. Idempotent.

    Multi-actives autorisé (LOT réplication itération 1) : on n'écrase pas
    les choix de l'admin. Si une stratégie env est déjà déclarée mais désactivée,
    on respecte le choix admin (on ne ré-active pas).
    """
    requested = settings.replication_strategy
    label = _label_for(requested)
    config = _config_from_env()

    # Upsert idempotent (insère si label inconnu, sinon update config).
    new_id = await repo.upsert_strategy(
        conn,
        type_=requested,
        label=label,
        description=_description_for(requested),
        config=config,
    )

    # Si AUCUNE stratégie n'est active, on active celle de l'env (cas premier
    # démarrage). Si l'admin a déjà activé/désactivé manuellement, on respecte.
    active_rows = await repo.list_active(conn)
    if not active_rows:
        await repo.activate_strategy(conn, new_id)
        logger.info(
            "replication_strategy_seeded_active",
            type=requested,
            strategy_id=str(new_id),
        )
    else:
        logger.info(
            "replication_strategy_already_active",
            active_count=len(active_rows),
            env_type=requested,
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
    """Active une stratégie. Plusieurs stratégies peuvent être actives en
    parallèle (multi-active depuis la migration 026).
    """
    return await repo.activate_strategy(conn, strategy_id)


async def deactivate(
    conn: asyncpg.Connection[asyncpg.Record],
    strategy_id: UUID,
) -> bool:
    """Désactive une stratégie sans toucher aux autres."""
    return await repo.deactivate_strategy(conn, strategy_id)


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
