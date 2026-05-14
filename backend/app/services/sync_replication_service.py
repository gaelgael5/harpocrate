"""Orchestrateur réplication MQTT (LOT_21B).

Démarre/arrête publisher + consumer dans le lifespan FastAPI si
`HARPOCRATE_SYNC_ENABLED=true`. Active aussi le flag SQL `sync_enabled` côté
DB pour que les triggers commencent à insérer dans sync_log.
"""

from __future__ import annotations

import json

import asyncpg

from app.core.config import settings
from app.core.logging import logger
from app.core.sync_consumer import SyncConsumer
from app.core.sync_publisher import SyncPublisher

_publisher: SyncPublisher | None = None
_consumer: SyncConsumer | None = None


async def _set_sync_enabled_in_db(
    conn: asyncpg.Connection[asyncpg.Record],
    enabled: bool,
) -> None:
    await conn.execute(
        """
        INSERT INTO system_metadata (key, value, updated_at)
        VALUES ('sync_enabled', $1::jsonb, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        json.dumps(enabled),
    )


async def _set_instance_id_session(
    pool: asyncpg.Pool[asyncpg.Record],
    instance_id: str,
) -> None:
    """Setting Postgres run-time pour que le trigger lise harpocrate.instance_id."""
    # Ne peut pas être SET LOCAL ici (hors transaction) ; on utilise SET (session)
    # sur le pool. Note : asyncpg recycle les connexions — chaque acquisition
    # neuve hérite des SET via le pool init_func.
    async with pool.acquire() as conn:
        await conn.execute(
            f"SET harpocrate.instance_id = '{instance_id}'"
        )


async def init_sync_replication(
    pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Démarre publisher + consumer si sync activé. Idempotent (no-op si déjà fait)."""
    global _publisher, _consumer
    if not settings.sync_enabled:
        async with pool.acquire() as conn:
            await _set_sync_enabled_in_db(conn, False)
        logger.info("sync_replication_disabled")
        return
    if not settings.sync_mqtt_host:
        logger.warning(
            "sync_replication_misconfigured",
            reason="HARPOCRATE_SYNC_MQTT_HOST is empty — disabling",
        )
        return

    async with pool.acquire() as conn:
        await _set_sync_enabled_in_db(conn, True)
    await _set_instance_id_session(pool, settings.instance_id)

    _publisher = SyncPublisher(
        mqtt_host=settings.sync_mqtt_host,
        mqtt_port=settings.sync_mqtt_port,
        mqtt_username=settings.sync_mqtt_username or None,
        mqtt_password=settings.sync_mqtt_password or None,
        instance_id=settings.instance_id,
        cluster_id=settings.sync_cluster_id,
    )
    _consumer = SyncConsumer(
        mqtt_host=settings.sync_mqtt_host,
        mqtt_port=settings.sync_mqtt_port,
        mqtt_username=settings.sync_mqtt_username or None,
        mqtt_password=settings.sync_mqtt_password or None,
        instance_id=settings.instance_id,
        cluster_id=settings.sync_cluster_id,
    )
    await _publisher.start()
    await _consumer.start()
    logger.info(
        "sync_replication_started",
        cluster=settings.sync_cluster_id,
        broker=f"{settings.sync_mqtt_host}:{settings.sync_mqtt_port}",
    )


async def stop_sync_replication() -> None:
    global _publisher, _consumer
    if _consumer is not None:
        await _consumer.stop()
        _consumer = None
    if _publisher is not None:
        await _publisher.stop()
        _publisher = None


def get_publisher() -> SyncPublisher | None:
    return _publisher


def get_consumer() -> SyncConsumer | None:
    return _consumer
