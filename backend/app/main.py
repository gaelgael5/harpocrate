"""FastAPI app — lifespan gère le pool asyncpg, JWKS, cluster sync (LOT_21A)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1 import (
    admin_anomalies,
    admin_backups,
    admin_install_mode,
    admin_maintenance,
    admin_pairing_exec,
    admin_remote_backups,
    admin_replication,
    admin_replication_pairing,
    admin_replication_sync,
    admin_scheduled_backups,
    admin_secret_types,
    admin_snapshots,
    admin_system,
    api_key_openapi,
    api_keys,
    api_keys_self,
    apps,
    audit_log,
    auth,
    auth_local,
    auth_recovery,
    config_keycloak,
    config_public,
    grants,
    health,
    identity_management,
    me_wallet_environments,
    sdk_downloads,
    secrets,
    users,
    wallets,
    webhooks_notify,
)
from app.core.cluster_sync import get_cluster_sync, init_cluster_sync
from app.core.config import settings
from app.core.jwks_cache import prefetch_jwks
from app.core.logging import configure_logging, logger
from app.db.pool import close_pool, get_pool, init_pool
from app.db.repositories import recovery_sessions as recovery_repo
from app.middleware.cluster_coherence import cluster_coherence_middleware
from app.services import local_admin_bootstrap
from app.services import replication as replication_svc
from app.services import scheduled_backups_scheduler as scheduled_sched_svc
from app.services import seed_types as seed_svc
from app.services import snapshot_scheduler as sched_svc
from app.services import sync_replication_service as sync_svc
from app.services import wallets as wallets_svc
from app.services.secret_paths import InvalidSecretPath
from migrations.apply_migrations import apply_migrations

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "starting",
        version="0.1.0",
        public_url=settings.public_url,
        instance_id=settings.instance_id,
    )
    await init_pool()
    await apply_migrations()
    if settings.keycloak_configured:
        await prefetch_jwks()
    else:
        logger.info("keycloak_not_configured_skipping_jwks_prefetch")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await seed_svc.seed_system_types(conn)
        # LOT_20 — s'assurer que la stratégie de réplication env est active.
        await replication_svc.ensure_env_strategy_active(conn)

    # LOT_56 — provisionne la row `users` du local-admin (is_system=TRUE) pour
    # qu'il puisse être référencé dans `audit_log.actor_user_id`. No-op si
    # admin_local_enabled=False.
    if settings.admin_local_enabled:
        await local_admin_bootstrap.ensure_local_admin_user(pool)

    # LOT_21A — démarre la sync cluster (LISTEN/NOTIFY + refresh 5s).
    # Le start() effectue un refresh initial AVANT de retourner, donc l'app
    # n'accepte aucun trafic tant que `cluster_state` n'est pas synchronisé.
    # ClusterSync ne capture plus le pool — chaque op fetch via get_pool()
    # (résilience à refresh_pool() post-pairing standby).
    cluster_sync = init_cluster_sync()
    await cluster_sync.start()

    # LOT_21B — réplication MQTT inter-instances (no-op si HARPOCRATE_SYNC_ENABLED=false).
    await sync_svc.init_sync_replication(pool)

    scheduler = sched_svc.init_scheduler()
    try:
        await scheduler.start()
    except Exception as exc:
        logger.warning("snapshot_scheduler_start_failed", error=str(exc))

    # Sauvegardes planifiées (cron-like) — boucle in-process avec asyncio.Lock
    # global pour sérialisation. Indépendant du snapshot scheduler ci-dessus.
    scheduled_backups_scheduler = scheduled_sched_svc.init_scheduler()
    try:
        await scheduled_backups_scheduler.start()
    except Exception as exc:
        logger.warning("scheduled_backups_scheduler_start_failed", error=str(exc))

    # Closures background : on n'utilise PAS la variable `pool` du lifespan
    # (qui pointe vers l'ancien pool après refresh_pool post-pairing). Chaque
    # tick refait `await get_pool()` (importé en tête) pour le pool actuel.
    async def _wallet_purge_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                current_pool = await get_pool()
                async with current_pool.acquire() as conn:
                    await wallets_svc.purge_expired_wallets(conn)
            except Exception as exc:
                logger.warning("wallet_purge_failed", error=str(exc))

    purge_task = asyncio.create_task(_wallet_purge_loop())

    # LOT réplication itération 1 — refresh périodique de l'état des standby
    # (lit pg_stat_replication côté master, met à jour replication_nodes).
    # Toutes les 30s : assez serré pour voir les bascules, pas trop pour
    # ne pas spammer le master.
    async def _replication_refresh_loop() -> None:
        from app.services import streaming_replication as repl_svc

        while True:
            await asyncio.sleep(30)
            try:
                current_pool = await get_pool()
                async with current_pool.acquire() as conn:
                    await repl_svc.refresh_nodes_state(conn)
            except Exception as exc:
                logger.warning("replication_refresh_failed", error=str(exc))

    replication_refresh_task = asyncio.create_task(_replication_refresh_loop())

    # LOT réplication itération 2 — purge horaire des observations > 7 jours.
    async def _replication_purge_loop() -> None:
        from app.services import streaming_replication as repl_svc

        while True:
            await asyncio.sleep(3600)
            try:
                current_pool = await get_pool()
                async with current_pool.acquire() as conn:
                    await repl_svc.purge_old_observations(conn)
            except Exception as exc:
                logger.warning("replication_purge_failed", error=str(exc))

    replication_purge_task = asyncio.create_task(_replication_purge_loop())

    # LOT_57 — worker d'expiration des sessions de recovery (toutes les 5 min).
    async def _recovery_expire_loop() -> None:
        while True:
            await asyncio.sleep(300)
            try:
                current_pool = await get_pool()
                async with current_pool.acquire() as conn:
                    expired = await recovery_repo.expire_pending(conn)
                if expired > 0:
                    logger.info("recovery_sessions_expired", count=expired)
            except Exception as exc:
                logger.warning("recovery_expire_failed", error=str(exc))

    recovery_expire_task = asyncio.create_task(_recovery_expire_loop())

    try:
        yield
    finally:
        # LOT_21A — graceful shutdown. uvicorn gère déjà `timeout_graceful_shutdown`
        # (drain des requêtes en cours). On stop ici les tâches de fond dans
        # l'ordre inverse du démarrage.
        logger.info("shutdown_initiated", instance_id=settings.instance_id)
        purge_task.cancel()
        recovery_expire_task.cancel()
        replication_refresh_task.cancel()
        replication_purge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await purge_task
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await recovery_expire_task
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await replication_refresh_task
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await replication_purge_task
        await scheduler.stop()
        await scheduled_backups_scheduler.stop()
        await sync_svc.stop_sync_replication()
        sync = get_cluster_sync()
        if sync is not None:
            await sync.stop()
        await close_pool()
        logger.info("shutdown_complete", instance_id=settings.instance_id)


app = FastAPI(
    title="Harpocrate",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(InvalidSecretPath)
async def _invalid_secret_path_handler(_request: Request, exc: InvalidSecretPath) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_secret_path", "message": str(exc)},
    )


# ─── Middlewares ──────────────────────────────────────────────────────────────
#
# RÈGLE DE SÉCURITÉ : les chemins /secrets ne doivent JAMAIS avoir leur body
# loggé. Le middleware log_requests ne lit pas le body ; il marque seulement
# body_logged=False pour les chemins secrets (documentaire).
#
# LOT_21A : le `cluster_coherence_middleware` remplace l'ancien
# `maintenance_middleware`. Il bloque maintenance + epoch incohérent.


@app.middleware("http")
async def _cluster_middleware(request: Request, call_next: object) -> Response:
    import typing

    _call_next = typing.cast("typing.Callable[[Request], typing.Awaitable[Response]]", call_next)
    return await cluster_coherence_middleware(request, _call_next)


@app.middleware("http")
async def log_requests(request: Request, call_next: object) -> Response:
    """Log HTTP requests. Body NEVER read or logged for /secrets paths."""
    import typing

    _call_next = typing.cast("typing.Callable[[Request], typing.Awaitable[Response]]", call_next)
    path = request.url.path
    is_secrets_path = "/secrets" in path
    body_logged = not is_secrets_path

    response = await _call_next(request)

    logger.info(
        "http_request",
        method=request.method,
        path=path,
        status=response.status_code,
        body_logged=body_logged,
    )
    return response


# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(admin_install_mode.router, prefix="/v1")
app.include_router(admin_maintenance.router, prefix="/v1")
app.include_router(admin_backups.router, prefix="/v1")
app.include_router(admin_remote_backups.router, prefix="/v1")
app.include_router(admin_scheduled_backups.router, prefix="/v1")
app.include_router(admin_replication.router, prefix="/v1")
app.include_router(admin_replication_pairing.router, prefix="/v1")
app.include_router(admin_pairing_exec.router, prefix="/v1")
app.include_router(admin_replication_sync.router, prefix="/v1")
app.include_router(admin_snapshots.router, prefix="/v1")
app.include_router(admin_secret_types.router, prefix="/v1")
app.include_router(admin_secret_types.public_router, prefix="/v1")
app.include_router(admin_system.router, prefix="/v1")
app.include_router(admin_anomalies.router, prefix="/v1")
app.include_router(health.router, prefix="/v1")
app.include_router(config_public.router, prefix="/v1")
app.include_router(config_keycloak.router, prefix="/v1")
app.include_router(auth_local.router, prefix="/v1")
app.include_router(auth_recovery.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
app.include_router(wallets.router, prefix="/v1")
app.include_router(grants.router, prefix="/v1")
app.include_router(grants.my_grant_router, prefix="/v1")
app.include_router(users.router, prefix="/v1")
app.include_router(secrets.router, prefix="/v1")
app.include_router(api_keys.router, prefix="/v1")
app.include_router(api_keys_self.router, prefix="/v1")
app.include_router(audit_log.router, prefix="/v1")
app.include_router(apps.router, prefix="/v1")
app.include_router(api_key_openapi.router, prefix="/v1")
app.include_router(identity_management.router, prefix="/v1")
app.include_router(me_wallet_environments.router, prefix="/v1")
app.include_router(sdk_downloads.router, prefix="/v1")
app.include_router(webhooks_notify.router, prefix="/v1")
