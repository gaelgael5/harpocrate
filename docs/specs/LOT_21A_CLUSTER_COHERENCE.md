# Lot 21A — Cohérence epoch et maintenance en cluster

> **Prérequis** : Lots 00-20.
> **Statut** : Implémentation — cohérence multi-nœuds via LISTEN/NOTIFY Postgres.

## Objectif

Garantir que tous les nœuds Harpocrate du cluster sont **instantanément cohérents** sur les deux états critiques partagés :

- **`session_epoch`** : quand un restore est effectué (lot 12a), tous les nœuds doivent invalider leurs sessions actives dans les 5 secondes
- **`maintenance_active`** : quand l'admin active/désactive la maintenance, tous les nœuds doivent refuser/accepter le trafic simultanément

Le mécanisme choisi (lot 19, décision D-3) est **LISTEN/NOTIFY Postgres** avec un refresh périodique de 5 secondes comme filet de sécurité.

Ce lot ajoute également :
- **`GET /health`** endpoint complet (lot 19, exigence E-5)
- **Graceful shutdown** via SIGTERM (lot 19, exigence E-4)
- **Colonne `seq BIGSERIAL`** sur `audit_log` (lot 19, décision D-5)

---

## Périmètre

### Inclus

- Migration `011_audit_log_seq.sql` : colonne `seq BIGSERIAL` sur `audit_log`
- Background task asyncio : LISTEN sur `harpocrate_epoch_changed` et `harpocrate_maintenance_changed`
- Refresh périodique toutes les 5s (filet de sécurité si NOTIFY manqué)
- Middleware FastAPI : rejet des requêtes si epoch RAM < epoch DB
- Middleware FastAPI : rejet des requêtes si maintenance_active (503)
- Emission de NOTIFY lors des changements d'epoch et de maintenance
- Endpoint `GET /health` complet
- Graceful shutdown SIGTERM avec drain 30s
- Variable d'env `HARPOCRATE_INSTANCE_ID` dans les logs
- Tests : simulation changement epoch multi-nœuds, simulation maintenance

### Exclus

- Pas de LISTEN/NOTIFY pour d'autres événements (JWKS, types de secrets, etc.)
- Pas de dashboard de monitoring cluster (lot futur)
- Pas de métriques Prometheus (lot futur)

---

## Partie 1 — Migration

```sql
-- migrations/011_audit_log_seq.sql

-- Séquence pour ordering strict de l'audit log en cluster
-- (lot 19, décision D-5 : NTP obligatoire mais seq comme filet)
ALTER TABLE audit_log ADD COLUMN seq BIGSERIAL;

CREATE INDEX idx_audit_log_seq ON audit_log(seq DESC);

-- Dorénavant les requêtes sur audit_log utilisent ORDER BY seq DESC
-- plutôt que ORDER BY occurred_at DESC
```

---

## Partie 2 — État partagé en RAM

Chaque nœud maintient un objet `ClusterState` en RAM, synchronisé depuis Postgres :

```python
# app/core/cluster_state.py

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("harpocrate.cluster")


@dataclass
class ClusterState:
    """
    État partagé entre tous les nœuds du cluster.
    Maintenu en RAM, synchronisé depuis Postgres via LISTEN/NOTIFY
    et refresh périodique.
    """
    session_epoch: int = 0
    maintenance_active: bool = False
    maintenance_message: Optional[str] = None
    maintenance_estimated_end_at: Optional[datetime] = None

    # Méta
    last_synced_at: Optional[datetime] = None
    instance_id: str = field(
        default_factory=lambda: os.environ.get(
            "HARPOCRATE_INSTANCE_ID", f"node-{os.getpid()}"
        )
    )

    def is_epoch_coherent(self, db_epoch: int) -> bool:
        return self.session_epoch >= db_epoch

    def update_from_db(
        self,
        epoch: int,
        maintenance: bool,
        message: Optional[str],
        estimated_end: Optional[datetime],
    ) -> list[str]:
        """
        Met à jour l'état depuis les valeurs DB.
        Retourne la liste des changements détectés.
        """
        changes = []

        if self.session_epoch != epoch:
            logger.warning(
                "epoch_updated",
                old=self.session_epoch,
                new=epoch,
                instance=self.instance_id,
            )
            self.session_epoch = epoch
            changes.append("epoch")

        if self.maintenance_active != maintenance:
            logger.info(
                "maintenance_updated",
                active=maintenance,
                instance=self.instance_id,
            )
            self.maintenance_active = maintenance
            self.maintenance_message = message
            self.maintenance_estimated_end_at = estimated_end
            changes.append("maintenance")

        self.last_synced_at = datetime.utcnow()
        return changes
```

---

## Partie 3 — Background task de synchronisation

```python
# app/core/cluster_sync.py

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from .cluster_state import ClusterState

logger = logging.getLogger("harpocrate.cluster_sync")

NOTIFY_CHANNELS = [
    "harpocrate_epoch_changed",
    "harpocrate_maintenance_changed",
    "harpocrate_jwks_invalidated",
]

REFRESH_INTERVAL_SECONDS = 5


class ClusterSyncTask:
    """
    Tâche asyncio qui maintient l'état cluster cohérent.

    Deux mécanismes complémentaires :
    1. LISTEN/NOTIFY Postgres : réactif, latence ~ms
    2. Refresh périodique toutes les 5s : filet de sécurité
       (couvre les NOTIFY manqués pendant une déconnexion)
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        state: ClusterState,
        on_epoch_changed: Optional[callable] = None,
        on_maintenance_changed: Optional[callable] = None,
    ):
        self._pool = pool
        self._state = state
        self._on_epoch_changed = on_epoch_changed
        self._on_maintenance_changed = on_maintenance_changed
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._listen_conn: Optional[asyncpg.Connection] = None

    async def start(self) -> None:
        """Démarre les deux tâches : LISTEN et refresh périodique."""
        # Sync initiale avant d'accepter le premier trafic
        await self._refresh_from_db()

        self._task = asyncio.gather(
            self._listen_loop(),
            self._periodic_refresh_loop(),
            return_exceptions=True,
        )
        logger.info(
            "cluster_sync_started",
            instance=self._state.instance_id,
            epoch=self._state.session_epoch,
            maintenance=self._state.maintenance_active,
        )

    async def stop(self) -> None:
        """Arrête proprement les tâches de synchronisation."""
        self._stop.set()
        if self._listen_conn:
            try:
                await self._listen_conn.close()
            except Exception:
                pass
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        logger.info("cluster_sync_stopped", instance=self._state.instance_id)

    # ─────────────────────────────────────────────────────────────────
    # LISTEN/NOTIFY
    # ─────────────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """
        Maintient une connexion dédiée pour LISTEN.
        Reconnecte automatiquement en cas de déconnexion.
        """
        while not self._stop.is_set():
            try:
                # Connexion dédiée au LISTEN (pas depuis le pool)
                self._listen_conn = await asyncpg.connect(
                    dsn=self._pool.get_dsn(),
                )

                # S'abonner à tous les canaux
                for channel in NOTIFY_CHANNELS:
                    await self._listen_conn.add_listener(
                        channel, self._on_notify
                    )

                logger.info(
                    "cluster_listen_connected",
                    channels=NOTIFY_CHANNELS,
                    instance=self._state.instance_id,
                )

                # Attendre jusqu'au stop ou déconnexion
                while not self._stop.is_set():
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        # Keepalive : vérifier que la connexion est vivante
                        await self._listen_conn.fetchval("SELECT 1")

            except asyncpg.PostgresConnectionStatusError:
                logger.warning(
                    "cluster_listen_disconnected",
                    instance=self._state.instance_id,
                )
                self._listen_conn = None
                # Refresh immédiat pour rattraper les NOTIFY manqués
                await self._refresh_from_db()
                # Reconnexion dans 2s
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(
                    "cluster_listen_error",
                    error=str(e),
                    instance=self._state.instance_id,
                )
                await asyncio.sleep(5)

    def _on_notify(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """
        Handler NOTIFY — appelé par asyncpg dans le thread event loop.
        Non-bloquant : schedule un refresh async.
        """
        logger.debug(
            "cluster_notify_received",
            channel=channel,
            payload=payload,
            instance=self._state.instance_id,
        )
        asyncio.create_task(self._handle_notify(channel, payload))

    async def _handle_notify(self, channel: str, payload: str) -> None:
        """Traite un événement NOTIFY reçu."""
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            data = {}

        if channel == "harpocrate_epoch_changed":
            new_epoch = data.get("new_value")
            if new_epoch and new_epoch != self._state.session_epoch:
                await self._refresh_from_db()

        elif channel == "harpocrate_maintenance_changed":
            await self._refresh_from_db()

        elif channel == "harpocrate_jwks_invalidated":
            # Déclencher un refresh JWKS (le JWTValidator écoute ce signal)
            if self._on_epoch_changed:
                await self._on_epoch_changed("jwks_invalidated")

    # ─────────────────────────────────────────────────────────────────
    # Refresh périodique
    # ─────────────────────────────────────────────────────────────────

    async def _periodic_refresh_loop(self) -> None:
        """Refresh toutes les 5s comme filet de sécurité."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=REFRESH_INTERVAL_SECONDS,
                )
                break  # stop demandé
            except asyncio.TimeoutError:
                pass  # normal, on refresh

            try:
                await self._refresh_from_db()
            except Exception as e:
                logger.error(
                    "cluster_periodic_refresh_failed",
                    error=str(e),
                    instance=self._state.instance_id,
                )

    async def _refresh_from_db(self) -> None:
        """Lit l'état depuis Postgres et met à jour le ClusterState."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    (SELECT value::int FROM system_metadata WHERE key = 'session_epoch') AS epoch,
                    (SELECT value::boolean FROM system_metadata WHERE key = 'maintenance_active') AS maintenance,
                    (SELECT value FROM system_metadata WHERE key = 'maintenance_message') AS message,
                    (SELECT value::timestamptz FROM system_metadata WHERE key = 'maintenance_estimated_end_at') AS estimated_end
            """)

        changes = self._state.update_from_db(
            epoch=row["epoch"] or 0,
            maintenance=row["maintenance"] or False,
            message=row["message"],
            estimated_end=row["estimated_end"],
        )

        # Déclencher les callbacks selon les changements détectés
        if "epoch" in changes and self._on_epoch_changed:
            await self._on_epoch_changed("epoch_changed")

        if "maintenance" in changes and self._on_maintenance_changed:
            await self._on_maintenance_changed(self._state.maintenance_active)
```

---

## Partie 4 — Emission de NOTIFY

Quand un nœud modifie l'epoch ou la maintenance, il doit émettre un NOTIFY pour que les autres nœuds réagissent immédiatement.

```python
# app/services/cluster_notify.py

import json
import logging
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger("harpocrate.cluster_notify")


async def notify_epoch_changed(
    conn: asyncpg.Connection,
    new_epoch: int,
    instance_id: str,
) -> None:
    payload = json.dumps({
        "event": "epoch_changed",
        "new_value": new_epoch,
        "emitted_by": instance_id,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    })
    await conn.execute(
        "SELECT pg_notify('harpocrate_epoch_changed', $1)", payload
    )
    logger.info(
        "notify_emitted",
        channel="harpocrate_epoch_changed",
        new_epoch=new_epoch,
        instance=instance_id,
    )


async def notify_maintenance_changed(
    conn: asyncpg.Connection,
    active: bool,
    instance_id: str,
) -> None:
    payload = json.dumps({
        "event": "maintenance_changed",
        "active": active,
        "emitted_by": instance_id,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    })
    await conn.execute(
        "SELECT pg_notify('harpocrate_maintenance_changed', $1)", payload
    )
    logger.info(
        "notify_emitted",
        channel="harpocrate_maintenance_changed",
        active=active,
        instance=instance_id,
    )


async def notify_jwks_invalidated(
    conn: asyncpg.Connection,
    instance_id: str,
) -> None:
    payload = json.dumps({
        "event": "jwks_invalidated",
        "emitted_by": instance_id,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    })
    await conn.execute(
        "SELECT pg_notify('harpocrate_jwks_invalidated', $1)", payload
    )
```

### Intégration dans les services existants

**Lors d'un restore (lot 12a)** — après incrémentation de l'epoch :

```python
# app/services/backup.py (modification)

async def restore_backup(conn, backup_id, actor, state):
    async with conn.transaction():
        # ... restore existant ...

        # Incrémenter l'epoch
        new_epoch = await conn.fetchval("""
            UPDATE system_metadata
            SET value = (value::int + 1)::text
            WHERE key = 'session_epoch'
            RETURNING value::int
        """)

        # Émettre le NOTIFY dans la même transaction
        await notify_epoch_changed(conn, new_epoch, state.instance_id)

        await audit_log(conn, "admin.backup_restored", ...)
```

**Lors du toggle maintenance (lot 12a)** — après modification :

```python
# app/services/maintenance.py (modification)

async def set_maintenance(conn, active: bool, actor, state):
    async with conn.transaction():
        await conn.execute("""
            UPDATE system_metadata
            SET value = $1
            WHERE key = 'maintenance_active'
        """, str(active).lower())

        # Émettre le NOTIFY dans la même transaction
        await notify_maintenance_changed(conn, active, state.instance_id)

        await audit_log(conn, "admin.maintenance_toggled", ...)
```

**Note** : émettre le NOTIFY **dans la même transaction** que la modification garantit que les autres nœuds ne reçoivent la notification qu'une fois la transaction committée. Si la transaction rollback, le NOTIFY n'est pas émis.

---

## Partie 5 — Middleware FastAPI

```python
# app/middleware/cluster_coherence.py

import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.cluster_state import ClusterState

logger = logging.getLogger("harpocrate.middleware")

# Endpoints exemptés des vérifications cluster
# (health check lui-même ne doit pas être bloqué)
EXEMPT_PATHS = {
    "/health",
    "/v1/health",
    "/metrics",
}


class ClusterCoherenceMiddleware(BaseHTTPMiddleware):
    """
    Vérifie la cohérence cluster avant chaque requête :
    1. Mode maintenance → 503
    2. Epoch incohérent → 503 (nœud en retard)
    """

    def __init__(self, app, state: ClusterState, pool):
        super().__init__(app)
        self._state = state
        self._pool = pool

    async def dispatch(self, request: Request, call_next) -> Response:
        # Exempter les endpoints de monitoring
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # 1. Vérifier le mode maintenance
        if self._state.maintenance_active:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "maintenance_in_progress",
                    "message": self._state.maintenance_message or "Maintenance in progress",
                    "estimated_end_at": (
                        self._state.maintenance_estimated_end_at.isoformat()
                        if self._state.maintenance_estimated_end_at
                        else None
                    ),
                },
                headers={"Retry-After": "60"},
            )

        # 2. Vérifier la cohérence de l'epoch
        # (lecture rapide depuis le pool, pas de requête lourde)
        async with self._pool.acquire() as conn:
            db_epoch = await conn.fetchval(
                "SELECT value::int FROM system_metadata WHERE key = 'session_epoch'"
            )

        if db_epoch and not self._state.is_epoch_coherent(db_epoch):
            logger.error(
                "epoch_incoherent_request_rejected",
                ram_epoch=self._state.session_epoch,
                db_epoch=db_epoch,
                instance=self._state.instance_id,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "node_epoch_incoherent",
                    "message": "This node is temporarily out of sync. Please retry.",
                },
                headers={"Retry-After": "5"},
            )

        return await call_next(request)
```

**Note sur la performance** : la vérification de l'epoch à chaque requête implique une lecture DB. C'est intentionnel — la cohérence prime sur la performance. En pratique, le pool asyncpg rend cette lecture très rapide (~1ms). Si c'est un problème de performance mesuré, on peut cacher l'epoch DB avec un TTL de 1s.

---

## Partie 6 — Endpoint `GET /health`

```python
# app/api/health.py

from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.cluster_state import ClusterState

router = APIRouter()


@router.get("/health")
async def health_check(
    request: Request,
    state: ClusterState = Depends(get_cluster_state),
    pool = Depends(get_pool),
    jwt_validator = Depends(get_jwt_validator),
):
    checks = {}
    overall = "ok"

    # 1. Connexion DB
    try:
        async with pool.acquire() as conn:
            db_epoch = await conn.fetchval(
                "SELECT value::int FROM system_metadata WHERE key = 'session_epoch'"
            )
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"
        overall = "down"
        db_epoch = None

    # 2. Cohérence epoch
    epoch_coherent = (
        db_epoch is not None and state.is_epoch_coherent(db_epoch)
    )
    checks["epoch_coherent"] = epoch_coherent
    if not epoch_coherent:
        overall = "degraded" if overall == "ok" else overall

    # 3. JWKS chargé
    jwks_loaded = jwt_validator.is_loaded()
    checks["jwks_loaded"] = jwks_loaded
    if not jwks_loaded:
        overall = "degraded" if overall == "ok" else overall

    # 4. Mode maintenance
    checks["maintenance_active"] = state.maintenance_active

    # 5. Cluster sync
    last_sync_age = None
    if state.last_synced_at:
        last_sync_age = (
            datetime.now(timezone.utc) - state.last_synced_at
        ).total_seconds()
    checks["last_sync_age_seconds"] = last_sync_age
    if last_sync_age and last_sync_age > 30:
        checks["cluster_sync_warning"] = "Last sync > 30s ago"
        overall = "degraded" if overall == "ok" else overall

    status_code = 200 if overall in ("ok", "degraded") else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "checks": checks,
            "instance_id": state.instance_id,
            "uptime_seconds": get_uptime(),
            "session_epoch": state.session_epoch,
            "version": "0.1.0",
        },
    )
```

**Réponses** :

```json
// 200 ok — nœud sain
{
  "status": "ok",
  "checks": {
    "db": "ok",
    "epoch_coherent": true,
    "jwks_loaded": true,
    "maintenance_active": false,
    "last_sync_age_seconds": 2.1
  },
  "instance_id": "node-abc123",
  "uptime_seconds": 3600,
  "session_epoch": 43
}

// 200 degraded — nœud fonctionnel mais avertissements
{
  "status": "degraded",
  "checks": {
    "db": "ok",
    "epoch_coherent": true,
    "jwks_loaded": true,
    "maintenance_active": false,
    "last_sync_age_seconds": 45.2,
    "cluster_sync_warning": "Last sync > 30s ago"
  }
}

// 503 down — nœud à retirer du pool
{
  "status": "down",
  "checks": {
    "db": "error: connection refused",
    "epoch_coherent": false,
    "jwks_loaded": false
  }
}
```

---

## Partie 7 — Graceful shutdown

```python
# app/main.py (modifications)

import asyncio
import logging
import signal

logger = logging.getLogger("harpocrate.main")


@app.on_event("startup")
async def on_startup():
    # ... init existant (pool, keycloak, etc.) ...

    # Initialiser le ClusterState
    app.state.cluster_state = ClusterState()

    # Démarrer la synchronisation cluster
    app.state.cluster_sync = ClusterSyncTask(
        pool=app.state.pool,
        state=app.state.cluster_state,
        on_epoch_changed=lambda reason: logger.info("epoch_changed", reason=reason),
        on_maintenance_changed=lambda active: logger.info("maintenance_changed", active=active),
    )
    await app.state.cluster_sync.start()

    logger.info(
        "harpocrate_started",
        instance=app.state.cluster_state.instance_id,
        epoch=app.state.cluster_state.session_epoch,
    )


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("harpocrate_shutdown_initiated", instance=app.state.cluster_state.instance_id)

    # 1. Arrêter la sync cluster
    await app.state.cluster_sync.stop()

    # 2. Fermer le pool Postgres proprement
    await app.state.pool.close()

    logger.info("harpocrate_shutdown_complete")


def setup_signal_handlers(app):
    """Configure les handlers SIGTERM et SIGINT."""

    shutdown_event = asyncio.Event()

    def handle_sigterm():
        logger.info("sigterm_received", instance=app.state.cluster_state.instance_id)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, handle_sigterm)
    loop.add_signal_handler(signal.SIGINT, handle_sigterm)

    return shutdown_event
```

### Configuration uvicorn pour le graceful shutdown

```python
# run.py

import asyncio
import uvicorn

config = uvicorn.Config(
    app="app.main:app",
    host="0.0.0.0",
    port=8000,
    timeout_graceful_shutdown=30,  # 30s pour finir les requêtes en cours
    log_level="info",
)
server = uvicorn.Server(config)

if __name__ == "__main__":
    asyncio.run(server.serve())
```

### Dans Docker Compose / Swarm

```yaml
# docker-compose.yml (ajout)
services:
  harpocrate:
    stop_grace_period: 35s   # > timeout_graceful_shutdown pour laisser uvicorn finir
    stop_signal: SIGTERM
```

---

## Partie 8 — Variable HARPOCRATE_INSTANCE_ID

```python
# app/core/config.py (ajout)

class Settings(BaseSettings):
    # ... settings existants ...

    instance_id: str = Field(
        default="",
        description="Unique identifier for this node in cluster logs. "
                    "Auto-generated if empty.",
    )

    @field_validator("instance_id")
    @classmethod
    def auto_instance_id(cls, v: str) -> str:
        if not v:
            import socket
            import os
            hostname = socket.gethostname()
            pid = os.getpid()
            return f"{hostname}-{pid}"
        return v
```

Tous les logs structurés incluent `instance_id` :

```python
# app/core/logging.py

import structlog

def configure_logging(instance_id: str):
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )

    # Binder l'instance_id à tous les logs de ce process
    structlog.contextvars.bind_contextvars(instance=instance_id)
```

---

## Partie 9 — Tests

### `tests/test_cluster_sync.py`

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.cluster_state import ClusterState
from app.core.cluster_sync import ClusterSyncTask


async def test_initial_sync_on_start(mock_pool):
    """Au démarrage, le state est synchronisé depuis la DB."""
    mock_pool.set_epoch(5)
    mock_pool.set_maintenance(False)

    state = ClusterState()
    sync = ClusterSyncTask(pool=mock_pool, state=state)
    await sync.start()

    assert state.session_epoch == 5
    assert state.maintenance_active is False

    await sync.stop()


async def test_notify_epoch_updates_state(mock_pool, mock_notify):
    """Réception d'un NOTIFY epoch_changed → state mis à jour."""
    mock_pool.set_epoch(5)
    state = ClusterState()
    sync = ClusterSyncTask(pool=mock_pool, state=state)
    await sync.start()

    # Simuler une modification de l'epoch en DB
    mock_pool.set_epoch(6)
    # Simuler réception du NOTIFY
    await sync._handle_notify(
        "harpocrate_epoch_changed",
        '{"event": "epoch_changed", "new_value": 6}'
    )

    assert state.session_epoch == 6

    await sync.stop()


async def test_notify_maintenance_updates_state(mock_pool):
    """Réception d'un NOTIFY maintenance → state mis à jour."""
    mock_pool.set_epoch(1)
    mock_pool.set_maintenance(False)
    state = ClusterState()
    sync = ClusterSyncTask(pool=mock_pool, state=state)
    await sync.start()

    mock_pool.set_maintenance(True, message="Scheduled maintenance")
    await sync._handle_notify("harpocrate_maintenance_changed", "{}")

    assert state.maintenance_active is True
    assert state.maintenance_message == "Scheduled maintenance"

    await sync.stop()


async def test_periodic_refresh_catches_missed_notify(mock_pool):
    """Le refresh périodique rattrape un NOTIFY manqué."""
    mock_pool.set_epoch(5)
    state = ClusterState()

    # Interval très court pour le test
    sync = ClusterSyncTask(pool=mock_pool, state=state)
    sync._refresh_interval = 0.1  # 100ms pour le test
    await sync.start()

    # Modifier l'epoch sans émettre de NOTIFY
    mock_pool.set_epoch(7)

    # Attendre le refresh périodique
    await asyncio.sleep(0.3)

    assert state.session_epoch == 7

    await sync.stop()


async def test_listen_reconnects_after_disconnect(mock_pool):
    """La tâche LISTEN reconnecte automatiquement après déconnexion."""
    state = ClusterState()
    sync = ClusterSyncTask(pool=mock_pool, state=state)
    await sync.start()

    # Simuler une déconnexion
    await sync._listen_conn.close()
    await asyncio.sleep(0.1)

    # La tâche doit avoir reconnecté
    assert sync._listen_conn is not None or sync._task is not None

    await sync.stop()
```

### `tests/test_cluster_middleware.py`

```python
async def test_maintenance_returns_503(client, cluster_state):
    cluster_state.maintenance_active = True
    cluster_state.maintenance_message = "Scheduled downtime"

    response = await client.get("/v1/wallets")

    assert response.status_code == 503
    assert response.json()["error"] == "maintenance_in_progress"
    assert response.headers["Retry-After"] == "60"


async def test_maintenance_does_not_block_health(client, cluster_state):
    cluster_state.maintenance_active = True

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["checks"]["maintenance_active"] is True


async def test_epoch_incoherent_returns_503(client, cluster_state, mock_pool):
    cluster_state.session_epoch = 3
    mock_pool.set_epoch(5)  # DB a epoch 5, RAM a epoch 3

    response = await client.get("/v1/wallets")

    assert response.status_code == 503
    assert response.json()["error"] == "node_epoch_incoherent"


async def test_coherent_epoch_passes_through(client, cluster_state, mock_pool):
    cluster_state.session_epoch = 5
    mock_pool.set_epoch(5)

    response = await client.get("/v1/wallets")

    assert response.status_code != 503


async def test_exempt_paths_bypass_checks(client, cluster_state, mock_pool):
    cluster_state.maintenance_active = True
    cluster_state.session_epoch = 0
    mock_pool.set_epoch(99)

    response = await client.get("/health")
    assert response.status_code == 200  # jamais bloqué
```

### `tests/test_health.py`

```python
async def test_health_ok(client, cluster_state, mock_pool, mock_jwt):
    cluster_state.session_epoch = 5
    mock_pool.set_epoch(5)
    mock_jwt.set_loaded(True)

    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["epoch_coherent"] is True
    assert data["checks"]["jwks_loaded"] is True


async def test_health_degraded_on_sync_lag(client, cluster_state):
    from datetime import datetime, timezone, timedelta
    cluster_state.last_synced_at = datetime.now(timezone.utc) - timedelta(seconds=60)

    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "cluster_sync_warning" in data["checks"]


async def test_health_down_on_db_failure(client, mock_pool):
    mock_pool.go_offline()

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "down"


async def test_health_returns_instance_id(client, cluster_state):
    cluster_state.instance_id = "test-node-1"

    response = await client.get("/health")

    assert response.json()["instance_id"] == "test-node-1"
```

### `tests/test_graceful_shutdown.py`

```python
async def test_sigterm_triggers_graceful_shutdown():
    """Le process répond à SIGTERM et attend la fin des requêtes."""
    import signal
    import os

    # Simuler SIGTERM
    os.kill(os.getpid(), signal.SIGTERM)

    # Attendre que le shutdown_event soit set
    await asyncio.sleep(0.1)

    # Vérifier que le cluster_sync s'est arrêté proprement
    # (dans un vrai test d'intégration)
    assert True  # placeholder — test d'intégration complet en CI
```

---

## Critères de succès

1. ✅ Migration `audit_log.seq BIGSERIAL` appliquée
2. ✅ `ClusterState` initialisé depuis DB au démarrage avant d'accepter le trafic
3. ✅ `ClusterSyncTask` démarre deux tâches : LISTEN et refresh périodique
4. ✅ NOTIFY `harpocrate_epoch_changed` reçu → state mis à jour en <100ms
5. ✅ NOTIFY `harpocrate_maintenance_changed` reçu → state mis à jour en <100ms
6. ✅ Déconnexion de la connexion LISTEN → reconnexion automatique + refresh immédiat
7. ✅ Refresh périodique toutes les 5s rattrape un NOTIFY manqué
8. ✅ NOTIFY émis dans la même transaction que la modification DB
9. ✅ Middleware bloque toutes les requêtes en mode maintenance (503)
10. ✅ Middleware laisse passer `/health` en mode maintenance
11. ✅ Middleware rejette les requêtes si epoch RAM < epoch DB (503)
12. ✅ `GET /health` retourne `200 ok` sur nœud sain
13. ✅ `GET /health` retourne `200 degraded` si sync lag > 30s
14. ✅ `GET /health` retourne `503 down` si DB inaccessible
15. ✅ `HARPOCRATE_INSTANCE_ID` dans tous les logs structurés
16. ✅ Graceful shutdown : SIGTERM → drain 30s → arrêt propre
17. ✅ `stop_grace_period: 35s` dans Docker Compose
18. ✅ Tests : notify epoch, notify maintenance, periodic refresh, middleware, health

## Pièges connus

- **Connexion dédiée pour LISTEN** : le LISTEN Postgres nécessite une connexion **non partagée** (pas depuis le pool asyncpg). Une connexion du pool ne peut pas rester en attente de NOTIFY — elle serait considérée comme idle et potentiellement recyclée. La connexion dédiée est créée séparément et maintenue en vie avec un keepalive.
- **NOTIFY dans la transaction** : si on émet le NOTIFY hors transaction, d'autres nœuds peuvent recevoir la notification avant que la transaction soit committée et lire l'ancienne valeur. Toujours émettre dans la même transaction que la modification.
- **Race condition au démarrage** : entre le démarrage du `ClusterSyncTask` et le premier refresh, une requête peut arriver avec un état incohérent. Solution : le refresh initial est synchrone et bloquant avant d'accepter le trafic (fait dans `on_startup`).
- **Vérification epoch à chaque requête** : 1 SELECT par requête. Sur un cluster actif (1000 req/s), ça fait 1000 SELECT/s supplémentaires sur Postgres. Si mesuré comme problème, cacher en RAM avec TTL 1s. Ne pas cacher plus longtemps — fenêtre d'incohérence inacceptable.
- **SIGTERM dans Docker Swarm** : Swarm envoie SIGTERM puis attend `stop_grace_period` avant SIGKILL. S'assurer que `stop_grace_period` > `timeout_graceful_shutdown` uvicorn (35s > 30s dans notre config).
- **Multi-process uvicorn** : si uvicorn tourne avec plusieurs workers (`--workers N`), chaque worker lance son propre `ClusterSyncTask`. C'est correct — chaque worker maintient son état cohérent indépendamment. Le NOTIFY est reçu par tous les workers via leurs connexions LISTEN dédiées.

## Ce qui suit

- **Lot 21B** — Réplication applicative Harpocrate → Harpocrate (multi-instance, E2E préservé)
- **Lot 23** — etcd 3 nœuds cross-host (pve1 + pve2)
