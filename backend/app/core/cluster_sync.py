"""Background task de synchronisation cluster (LOT_21A).

Maintient `cluster_state` en cohérence avec Postgres via DEUX mécanismes
complémentaires :

1. **LISTEN/NOTIFY** sur les canaux `harpocrate_*_changed` — réactif (~ms),
   sur une connexion asyncpg dédiée (pas depuis le pool).
2. **Refresh périodique 5s** — filet de sécurité pour rattraper les NOTIFY
   manqués pendant une déconnexion.

Au démarrage, un refresh initial est effectué AVANT de retourner — l'app
ne doit pas accepter de trafic avec un état RAM par défaut.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json

import asyncpg

from app.core.cluster_state import cluster_state
from app.core.config import settings
from app.core.logging import logger
from app.core.maintenance import maintenance_state
from app.services.cluster_notify import (
    CHANNEL_EPOCH,
    CHANNEL_JWKS,
    CHANNEL_MAINTENANCE,
)

REFRESH_INTERVAL_SECONDS = 5
LISTEN_KEEPALIVE_SECONDS = 30
LISTEN_RECONNECT_DELAY_SECONDS = 2

_NOTIFY_CHANNELS = (CHANNEL_EPOCH, CHANNEL_MAINTENANCE, CHANNEL_JWKS)


def _parse_dt(raw: object) -> datetime.datetime | None:
    """Parse ISO datetime depuis JSON. Tolère str/None/déjà datetime."""
    if raw is None:
        return None
    if isinstance(raw, datetime.datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


class ClusterSync:
    """Tâche asyncio long-running qui synchronise `cluster_state` avec Postgres."""

    def __init__(self, pool: asyncpg.Pool[asyncpg.Record]) -> None:
        self._pool = pool
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._listen_conn: asyncpg.Connection[asyncpg.Record] | None = None
        self._on_jwks_invalidated: asyncio.Event = asyncio.Event()
        self._inflight_notify_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Effectue un refresh initial puis démarre les boucles LISTEN + refresh."""
        await self._refresh_from_db()
        logger.info(
            "cluster_sync_started",
            epoch=cluster_state.session_epoch,
            maintenance=cluster_state.maintenance_active,
        )
        self._tasks = [
            asyncio.create_task(self._listen_loop(), name="cluster_listen"),
            asyncio.create_task(self._refresh_loop(), name="cluster_refresh"),
        ]

    async def stop(self) -> None:
        """Arrête proprement les deux boucles et ferme la connexion LISTEN."""
        self._stop_event.set()
        if self._listen_conn is not None:
            with contextlib.suppress(Exception):
                await self._listen_conn.close()
            self._listen_conn = None
        for task in self._tasks:
            task.cancel()
        # On attend que tout soit terminé en absorbant les CancelledError
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("cluster_sync_stopped")

    # ─── LISTEN/NOTIFY ────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Maintient une connexion dédiée pour LISTEN, reconnecte si déco."""
        while not self._stop_event.is_set():
            try:
                self._listen_conn = await asyncpg.connect(dsn=settings.db_dsn)
                for channel in _NOTIFY_CHANNELS:
                    await self._listen_conn.add_listener(channel, self._on_notify)
                logger.info("cluster_listen_connected", channels=list(_NOTIFY_CHANNELS))

                # Boucle keepalive : on attend stop, ou timeout pour ping
                while not self._stop_event.is_set():
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=LISTEN_KEEPALIVE_SECONDS,
                        )
                    except TimeoutError:
                        # Vérifie que la connexion est encore vivante
                        await self._listen_conn.fetchval("SELECT 1")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("cluster_listen_error", error=str(exc))
                if self._listen_conn is not None:
                    with contextlib.suppress(Exception):
                        await self._listen_conn.close()
                    self._listen_conn = None
                # Au reconnect, on rattrape via un refresh DB immédiat
                try:
                    await self._refresh_from_db()
                except Exception as refresh_exc:
                    logger.warning(
                        "cluster_refresh_after_disconnect_failed",
                        error=str(refresh_exc),
                    )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=LISTEN_RECONNECT_DELAY_SECONDS,
                    )

    def _on_notify(
        self,
        _connection: asyncpg.Connection[asyncpg.Record],
        _pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Handler asyncpg appelé dans le loop ; on schedule le traitement async."""
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            data = {}
        logger.debug("cluster_notify_received", channel=channel, payload_keys=list(data.keys()))
        # On garde la référence pour éviter qu'asyncio garbage-collecte la tâche
        # avant son achèvement (RUF006). Les tâches s'auto-déréférencent à la fin.
        task = asyncio.create_task(self._handle_notify(channel, data))
        self._inflight_notify_tasks.add(task)
        task.add_done_callback(self._inflight_notify_tasks.discard)

    async def _handle_notify(self, channel: str, data: dict[str, object]) -> None:
        """Traitement async d'un NOTIFY : on déclenche un refresh DB."""
        try:
            if channel == CHANNEL_JWKS:
                # Le module JWKS écoute cet event pour forcer un refresh
                self._on_jwks_invalidated.set()
                self._on_jwks_invalidated.clear()
                return
            await self._refresh_from_db()
        except Exception as exc:
            logger.warning("cluster_notify_handler_error", channel=channel, error=str(exc))

    # ─── Refresh périodique ──────────────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Refresh toutes les REFRESH_INTERVAL_SECONDS secondes."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=REFRESH_INTERVAL_SECONDS,
                )
                break  # stop demandé
            except TimeoutError:
                pass
            try:
                await self._refresh_from_db()
            except Exception as exc:
                logger.warning("cluster_periodic_refresh_failed", error=str(exc))

    async def _refresh_from_db(self) -> None:
        """Lit l'état partagé en DB et applique sur le `cluster_state`."""
        async with self._pool.acquire() as conn:
            epoch_row = await conn.fetchrow(
                "SELECT epoch FROM server_session_epoch LIMIT 1"
            )
            maint_row = await conn.fetchrow(
                "SELECT value FROM system_metadata WHERE key = 'maintenance_mode'"
            )

        epoch = int(epoch_row["epoch"]) if epoch_row else 0
        maint_raw = maint_row["value"] if maint_row else None
        if isinstance(maint_raw, str):
            try:
                maint_data: dict[str, object] = json.loads(maint_raw)
            except json.JSONDecodeError:
                maint_data = {}
        elif isinstance(maint_raw, dict):
            maint_data = maint_raw
        else:
            maint_data = {}

        active = bool(maint_data.get("active"))
        reason = maint_data.get("reason")
        if not isinstance(reason, str):
            reason = None

        changes = cluster_state.update_from_db(
            epoch=epoch,
            maintenance_active=active,
            maintenance_reason=reason,
            maintenance_started_at=_parse_dt(maint_data.get("started_at")),
            maintenance_effective_at=_parse_dt(maint_data.get("effective_at")),
            maintenance_estimated_end_at=_parse_dt(maint_data.get("estimated_end_at")),
        )

        # Compatibilité legacy : on synchronise aussi `maintenance_state` (utilisé
        # encore par admin_maintenance.py et le middleware historique).
        maintenance_state.active = active
        maintenance_state.reason = reason
        maintenance_state.started_at = cluster_state.maintenance_started_at
        maintenance_state.effective_at = cluster_state.maintenance_effective_at
        maintenance_state.estimated_end_at = cluster_state.maintenance_estimated_end_at

        if changes:
            logger.info(
                "cluster_state_refreshed",
                changes=changes,
                epoch=cluster_state.session_epoch,
                maintenance=cluster_state.maintenance_active,
            )


# Singleton accédé depuis le lifespan.
_sync: ClusterSync | None = None


def init_cluster_sync(pool: asyncpg.Pool[asyncpg.Record]) -> ClusterSync:
    global _sync
    _sync = ClusterSync(pool)
    return _sync


def get_cluster_sync() -> ClusterSync | None:
    return _sync
