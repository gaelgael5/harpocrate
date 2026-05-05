"""FastAPI app — lifespan gère le pool asyncpg, JWKS, cluster sync (LOT_21A)."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1 import (
    admin_backups,
    admin_maintenance,
    admin_remote_backups,
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
    config_keycloak,
    config_public,
    grants,
    health,
    identity_management,
    sdk_downloads,
    secrets,
    users,
    wallets,
)
from app.core.cluster_sync import get_cluster_sync, init_cluster_sync
from app.core.config import settings
from app.core.jwks_cache import prefetch_jwks
from app.core.logging import configure_logging, logger
from app.db.pool import close_pool, get_pool, init_pool
from app.middleware.cluster_coherence import cluster_coherence_middleware
from app.services import seed_types as seed_svc
from app.services import snapshot_scheduler as sched_svc
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
    await prefetch_jwks()

    pool = await get_pool()
    async with pool.acquire() as conn:
        await seed_svc.seed_system_types(conn)

    # LOT_21A — démarre la sync cluster (LISTEN/NOTIFY + refresh 5s).
    # Le start() effectue un refresh initial AVANT de retourner, donc l'app
    # n'accepte aucun trafic tant que `cluster_state` n'est pas synchronisé.
    cluster_sync = init_cluster_sync(pool)
    await cluster_sync.start()

    scheduler = sched_svc.init_scheduler(pool)
    try:
        await scheduler.start()
    except Exception as exc:
        logger.warning("snapshot_scheduler_start_failed", error=str(exc))

    async def _wallet_purge_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                async with pool.acquire() as conn:
                    await wallets_svc.purge_expired_wallets(conn)
            except Exception as exc:
                logger.warning("wallet_purge_failed", error=str(exc))

    purge_task = asyncio.create_task(_wallet_purge_loop())

    try:
        yield
    finally:
        # LOT_21A — graceful shutdown. uvicorn gère déjà `timeout_graceful_shutdown`
        # (drain des requêtes en cours). On stop ici les tâches de fond dans
        # l'ordre inverse du démarrage.
        logger.info("shutdown_initiated", instance_id=settings.instance_id)
        purge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await purge_task
        await scheduler.stop()
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
    _call_next = typing.cast(
        "typing.Callable[[Request], typing.Awaitable[Response]]", call_next
    )
    return await cluster_coherence_middleware(request, _call_next)


@app.middleware("http")
async def log_requests(request: Request, call_next: object) -> Response:
    """Log HTTP requests. Body NEVER read or logged for /secrets paths."""
    import typing

    _call_next = typing.cast(
        "typing.Callable[[Request], typing.Awaitable[Response]]", call_next
    )
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

app.include_router(admin_maintenance.router, prefix="/v1")
app.include_router(admin_backups.router, prefix="/v1")
app.include_router(admin_remote_backups.router, prefix="/v1")
app.include_router(admin_snapshots.router, prefix="/v1")
app.include_router(admin_secret_types.router, prefix="/v1")
app.include_router(admin_secret_types.public_router, prefix="/v1")
app.include_router(admin_system.router, prefix="/v1")
app.include_router(health.router, prefix="/v1")
app.include_router(config_public.router, prefix="/v1")
app.include_router(config_keycloak.router, prefix="/v1")
app.include_router(auth_local.router, prefix="/v1")
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
app.include_router(sdk_downloads.router, prefix="/v1")
