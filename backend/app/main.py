"""FastAPI app — lifespan gère le pool asyncpg et le cache JWKS."""
from __future__ import annotations

import asyncio
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
from app.core.config import settings
from app.core.jwks_cache import prefetch_jwks
from app.core.logging import configure_logging, logger
from app.core.maintenance import maintenance_state
from app.db.pool import close_pool, get_pool, init_pool
from migrations.apply_migrations import apply_migrations
from app.services import seed_types as seed_svc
from app.services import snapshot_scheduler as sched_svc
from app.services import wallets as wallets_svc
from app.services.secret_paths import InvalidSecretPath

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "starting",
        version="0.1.0",
        public_url=settings.public_url,
    )
    await init_pool()
    await apply_migrations()
    await prefetch_jwks()

    pool = await get_pool()
    async with pool.acquire() as conn:
        await seed_svc.seed_system_types(conn)
    scheduler = sched_svc.init_scheduler(pool)
    try:
        await scheduler.start()
    except Exception as exc:
        logger.warning("snapshot_scheduler_start_failed", error=str(exc))

    async def _wallet_purge_loop() -> None:
        while True:
            await asyncio.sleep(3600)  # toutes les heures
            try:
                async with pool.acquire() as conn:
                    await wallets_svc.purge_expired_wallets(conn)
            except Exception as exc:
                logger.warning("wallet_purge_failed", error=str(exc))

    purge_task = asyncio.create_task(_wallet_purge_loop())

    try:
        yield
    finally:
        purge_task.cancel()
        await scheduler.stop()
        await close_pool()
        logger.info("stopped")


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


# ─── Middleware : log des requêtes HTTP ───────────────────────────────────────
#
# RÈGLE DE SÉCURITÉ : les chemins /secrets ne doivent JAMAIS avoir leur body loggé.
# Ce middleware ne lit pas du tout le body ; il se contente de noter body_logged=False
# pour les chemins secrets afin de documenter explicitement l'intention.
# Les handlers eux-mêmes ne loguent jamais les champs encrypted_value.


@app.middleware("http")
async def maintenance_middleware(request: Request, call_next: object) -> Response:
    """Bloque toutes les requêtes non-admin avec 503 en mode maintenance."""
    import typing
    _call_next = typing.cast("typing.Callable[[Request], typing.Awaitable[Response]]", call_next)
    if maintenance_state.active:
        path = request.url.path
        if (
            path.startswith("/v1/admin/")
            or path == "/v1/health"
        ):
            return await _call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "error": "maintenance_in_progress",
                "estimated_end_at": (
                    maintenance_state.estimated_end_at.isoformat()
                    if maintenance_state.estimated_end_at else None
                ),
            },
            headers={"Retry-After": "60"},
        )
    return await _call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next: object) -> Response:
    """Log HTTP requests. Body NEVER read or logged for /secrets paths."""
    import typing

    _call_next = typing.cast("typing.Callable[[Request], typing.Awaitable[Response]]", call_next)
    path = request.url.path
    # Détecte tout chemin contenant /secrets (liste ou item)
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
