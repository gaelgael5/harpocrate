"""Scheduler des sauvegardes planifiées (LOT scheduled backups).

Boucle asyncio in-process :
  - Tick toutes les 60s : `SELECT ... WHERE enabled AND next_run_at <= NOW()`
  - Sérialisation : `asyncio.Lock` global. Si un schedule tourne, le suivant
    attend (skip ce tick, sera re-due au tick suivant car next_run_at n'a pas
    changé).
  - Politique de miss : au démarrage, pour chaque schedule en retard de plus
    de `miss_threshold_minutes`, on saute (recale next_run_at au prochain
    créneau futur, log warning).

L'API admin (`run_now`) acquiert le MÊME lock que le scheduler — un déclenchement
manuel attend qu'un éventuel run en cours soit terminé. Évite tout doublon.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
import structlog

from app.db.repositories import scheduled_backups as repo
from app.services import scheduled_backups as svc


logger = structlog.get_logger(__name__)

# Tick fixed-rate. 60s est une granularité largement suffisante pour des
# planifications cron (qui s'expriment au mieux à la minute).
TICK_INTERVAL_SECONDS = 60


class ScheduledBackupsScheduler:
    """Boucle de tick + sérialisation des exécutions.

    Ne capture pas le pool au boot : chaque acquisition fetch le pool actuel
    via `app.db.pool.get_pool()`. Garantit la résilience face à
    `refresh_pool()` (déclenché après pairing standby).
    """

    def __init__(self) -> None:
        from app.services.backup_lock import get_global_backup_lock

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # Lock partagé avec le snapshot_scheduler : pas deux pg_dump en
        # parallèle. Sert aussi à sérialiser les runs de schedules entre eux
        # (tick auto + run-now).
        self._run_lock = get_global_backup_lock()

    @staticmethod
    async def _get_pool() -> asyncpg.Pool:
        from app.db.pool import get_pool

        return await get_pool()

    @property
    def run_lock(self) -> asyncio.Lock:
        """Exposé pour que l'endpoint `run-now` partage le lock."""
        return self._run_lock

    async def start(self) -> None:
        # Au démarrage : applique la politique de miss (skip + recalcule
        # next_run_at pour les schedules trop en retard).
        await self._apply_miss_policy_at_startup()

        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "scheduled_backups_scheduler_started",
            tick_interval_seconds=TICK_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._stop.set()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("scheduled_backups_scheduler_stopped")

    async def _apply_miss_policy_at_startup(self) -> None:
        """Pour chaque schedule due de plus de `miss_threshold_minutes`,
        recalcule `next_run_at` au prochain créneau futur. Évite les
        déclenchements en chaîne après un long down.
        """
        now = datetime.now(timezone.utc)
        async with (await self._get_pool()).acquire() as conn:
            schedules = await svc.list_schedules(conn)
            for sched in schedules:
                if not sched.enabled:
                    continue
                if not svc.is_miss(sched, now=now):
                    continue
                next_run = svc.compute_next_run(sched.cron_expression, after=now)
                await repo.update(
                    conn, schedule_id=sched.id, next_run_at=next_run
                )
                logger.warning(
                    "scheduled_backup_miss_skipped_at_startup",
                    schedule_id=str(sched.id),
                    schedule_name=sched.name,
                    miss_threshold_minutes=sched.miss_threshold_minutes,
                    new_next_run_at=next_run.isoformat(),
                )

    async def _run_loop(self) -> None:
        """Boucle de tick. Skip silencieusement si déjà locked (un autre
        run en cours)."""
        while not self._stop.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — on log et on continue
                logger.error("scheduled_backups_tick_failed", error=str(exc))

            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=TICK_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        """Un tick : récupère les due, exécute en série (sous lock)."""
        now = datetime.now(timezone.utc)
        async with (await self._get_pool()).acquire() as conn:
            due_rows = await repo.list_due(conn, now=now)
        if not due_rows:
            return

        # Si le lock est pris (run précédent encore en cours OU run-now
        # manuel en cours), on saute ce tick. Les schedules due restent due
        # (next_run_at non modifié) et seront retraités au prochain tick.
        if self._run_lock.locked():
            logger.info(
                "scheduled_backups_tick_skipped_lock_held",
                due_count=len(due_rows),
            )
            return

        async with self._run_lock:
            for row in due_rows:
                if self._stop.is_set():
                    return
                schedule = svc._row_to_dto(row)
                await self._execute_schedule(schedule)

    async def _execute_schedule(self, schedule: svc.ScheduledBackup) -> None:
        """Exécute un schedule + persiste le résultat + recalcule next_run_at."""
        started_at = datetime.now(timezone.utc)
        logger.info(
            "scheduled_backup_running",
            schedule_id=str(schedule.id),
            schedule_name=schedule.name,
            remote_id=str(schedule.remote_id) if schedule.remote_id else None,
        )

        result: svc.RunResult
        try:
            async with (await self._get_pool()).acquire() as conn:
                result = await svc.run_schedule(conn, schedule)
        except Exception as exc:  # noqa: BLE001 — on remonte tout pour persistance
            result = svc.RunResult(status="failed", error=f"unexpected: {exc}")

        # Recalcule next_run_at toujours, même en cas d'échec — sinon on
        # boucle indéfiniment sur le même schedule cassé.
        next_run = svc.compute_next_run(
            schedule.cron_expression, after=datetime.now(timezone.utc)
        )

        async with (await self._get_pool()).acquire() as conn:
            await repo.mark_run(
                conn,
                schedule_id=schedule.id,
                last_run_at=started_at,
                last_run_status=result.status,
                last_run_error=result.error,
                next_run_at=next_run,
            )

        if result.status == "ok":
            logger.info(
                "scheduled_backup_done",
                schedule_id=str(schedule.id),
                backup_id=str(result.backup_id) if result.backup_id else None,
                bytes_pushed=result.bytes_pushed,
                next_run_at=next_run.isoformat(),
            )
        elif result.status == "skipped":
            # Skip "rien-à-sauver" est un comportement normal et attendu — info,
            # pas warning. Évite de polluer les alertes de prod.
            logger.info(
                "scheduled_backup_skipped",
                schedule_id=str(schedule.id),
                schedule_name=schedule.name,
                reason=result.error,
                next_run_at=next_run.isoformat(),
            )
        else:
            logger.warning(
                "scheduled_backup_failed",
                schedule_id=str(schedule.id),
                error=result.error,
                next_run_at=next_run.isoformat(),
            )

    async def run_now(self, schedule_id: UUID) -> svc.RunResult:
        """Exécute manuellement un schedule (acquiert le même lock que la boucle).

        Utilisé par l'endpoint `POST /admin/scheduled-backups/{id}/run-now`.
        """
        async with self._run_lock:
            async with (await self._get_pool()).acquire() as conn:
                schedule = await svc.get_schedule(conn, schedule_id)
                if schedule is None:
                    return svc.RunResult(
                        status="failed", error="schedule not found"
                    )

            started_at = datetime.now(timezone.utc)
            try:
                async with (await self._get_pool()).acquire() as conn:
                    result = await svc.run_schedule(conn, schedule)
            except Exception as exc:  # noqa: BLE001
                result = svc.RunResult(
                    status="failed", error=f"unexpected: {exc}"
                )

            # On met à jour last_run_* mais on ne touche PAS à next_run_at —
            # un run manuel ne doit pas décaler le créneau planifié.
            async with (await self._get_pool()).acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scheduled_backup
                    SET last_run_at = $1, last_run_status = $2, last_run_error = $3
                    WHERE id = $4
                    """,
                    started_at,
                    result.status,
                    result.error,
                    schedule.id,
                )
            return result


# ─── Singleton module-level (init au lifespan, partagé par les endpoints) ────


_scheduler: ScheduledBackupsScheduler | None = None


def init_scheduler() -> ScheduledBackupsScheduler:
    """À appeler une fois dans le lifespan FastAPI. Idempotent (réutilise
    l'instance si déjà créée — utile pour le hot-reload uvicorn en dev).

    Ne prend plus de pool en argument : le scheduler fetch `get_pool()` à
    chaque tick, survit donc à `refresh_pool()` post-pairing.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = ScheduledBackupsScheduler()
    return _scheduler


def get_scheduler() -> ScheduledBackupsScheduler | None:
    """Retourne le scheduler initialisé, ou None si non encore démarré (tests)."""
    return _scheduler
