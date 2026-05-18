"""Scheduler de partitions journalières de `sync_log` — R-1/R-2.

À chaque tick horaire :
    1. Crée la partition pour `today` et `today+1` (idempotent).
    2. Drop les partitions journalières plus vieilles que
       `HARPOCRATE_SYNC_LOG_RETENTION_DAYS` (défaut 7).

La partition `sync_log_default` reste en place comme filet de sécurité —
elle catch les inserts hors fenêtre des partitions journalières. Le
scheduler ne la touche jamais.

Le scheduler tourne en standalone ET en mode cluster (les inserts dans
sync_log dépendent de `system_metadata.sync_enabled`, mais la création
de partitions est inoffensive même si la table reste vide).

S'appuie sur les deux fonctions PL/pgSQL de la migration 032 :
- `ensure_sync_log_partition(target_date DATE) RETURNS TEXT`
- `drop_old_sync_log_partitions(retention_days INT) RETURNS INT`
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, date, datetime, timedelta

import asyncpg

from app.core.config import settings
from app.core.logging import logger

# Tick toutes les heures : on n'a pas besoin de plus de précision —
# la partition du lendemain peut être créée 23h en avance sans pénalité.
_INTERVAL_SECONDS = 3600


def _today_utc() -> date:
    """Date UTC actuelle (référence pour les partitions journalières)."""
    return datetime.now(UTC).date()


async def ensure_partitions_window(
    conn: asyncpg.Connection[asyncpg.Record],
    days_ahead: int = 1,
) -> list[str]:
    """Crée les partitions pour `today, today+1, ..., today+days_ahead`.

    Idempotent : si la partition existe déjà, la fonction PL/pgSQL fait
    `CREATE TABLE IF NOT EXISTS` et ne lève pas. Retourne la liste des
    noms de partitions ciblés (créés OU déjà présents).
    """
    if days_ahead < 0:
        raise ValueError(f"days_ahead must be >= 0, got {days_ahead}")

    today = _today_utc()
    created: list[str] = []
    for offset in range(days_ahead + 1):
        target = today + timedelta(days=offset)
        name = await conn.fetchval("SELECT ensure_sync_log_partition($1)", target)
        if name is not None:
            created.append(name)
    return created


async def drop_old_partitions(
    conn: asyncpg.Connection[asyncpg.Record],
    retention_days: int,
) -> int:
    """Drop les partitions journalières plus vieilles que `retention_days` jours.

    Retourne le nombre de partitions effectivement supprimées.
    `sync_log_default` n'est jamais touchée.
    """
    return await conn.fetchval(
        "SELECT drop_old_sync_log_partitions($1)", retention_days
    )


class SyncLogPartitionScheduler:
    """Tick horaire : ensure aujourd'hui+demain, drop les anciens.

    Ne capture pas le pool : chaque acquire fetch `get_pool()` actuel
    (résilience à `refresh_pool()` post-pairing standby — même contrat
    que `SnapshotScheduler`).
    """

    def __init__(self, interval_seconds: int = _INTERVAL_SECONDS) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._interval_seconds = interval_seconds

    @staticmethod
    async def _get_pool() -> asyncpg.Pool[asyncpg.Record]:
        from app.db.pool import get_pool

        return await get_pool()

    async def start(self) -> None:
        """Premier tick synchrone (avant yield du lifespan) + démarre la boucle."""
        # Tick initial : crée les partitions today+tomorrow avant que toute
        # requête FastAPI ne puisse INSERT dans sync_log (sans cela, les
        # inserts d'aujourd'hui tomberaient dans `default` au démarrage).
        await self._tick()
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "sync_log_partition_scheduler_started",
            retention_days=settings.sync_log_retention_days,
            interval_seconds=self._interval_seconds,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._stop.set()
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _tick(self) -> None:
        """Un tick : ensure window + drop old. Erreurs loguées, pas relevées."""
        try:
            async with (await self._get_pool()).acquire() as conn:
                ensured = await ensure_partitions_window(conn, days_ahead=1)
                dropped = await drop_old_partitions(
                    conn, settings.sync_log_retention_days
                )
            if dropped > 0:
                logger.info(
                    "sync_log_partitions_dropped",
                    count=dropped,
                    retention_days=settings.sync_log_retention_days,
                )
            logger.debug(
                "sync_log_partition_tick",
                ensured=ensured,
                dropped=dropped,
            )
        except Exception as exc:
            logger.error("sync_log_partition_tick_failed", error=str(exc))

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            # Timeout normal = tick horaire. On suppress TimeoutError pour
            # repasser dans la boucle ; un set() de _stop sort proprement.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval_seconds,
                )

            if self._stop.is_set():
                return

            try:
                await self._tick()
            except asyncio.CancelledError:
                raise


_scheduler: SyncLogPartitionScheduler | None = None


def init_scheduler() -> SyncLogPartitionScheduler:
    """Singleton instance initialisée par le lifespan."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SyncLogPartitionScheduler()
    return _scheduler


def get_scheduler() -> SyncLogPartitionScheduler | None:
    """Pour tests et introspection."""
    return _scheduler
