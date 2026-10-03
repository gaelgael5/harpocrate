"""Tâche de fond du flux « Se connecter avec Harpocrate » : purge des demandes échues (D13).

Lancée par le lifespan FastAPI. Le pool est relu à chaque tick (il est recréé après un
pairing) ; une base momentanément injoignable ne fait que reporter la purge au tick suivant.
"""

from __future__ import annotations

import asyncio
import datetime

import asyncpg
import structlog

from app.db.pool import get_pool
from app.services.connect_exchange import purge_expired_requests

logger = structlog.get_logger(__name__)

# Une minute : une clé non livrée est révoquée au plus une minute après l'échéance de sa
# demande (15 min, D9).
PURGE_INTERVAL_SECONDS = 60


async def run_purge_loop() -> None:
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                deleted = await purge_expired_requests(
                    conn, now=datetime.datetime.now(datetime.UTC)
                )
            if deleted:
                logger.info("connect_requests_purged", count=deleted)
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
            logger.warning("connect_purge_failed", error_type=type(exc).__name__, error=str(exc))
