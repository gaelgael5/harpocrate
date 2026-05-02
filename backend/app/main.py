"""FastAPI app — lifespan gère le pool asyncpg et le cache JWKS."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.api.v1 import (
    api_keys,
    api_keys_self,
    apps,
    audit_log,
    auth,
    config_keycloak,
    config_public,
    grants,
    health,
    secrets,
    users,
    wallets,
)
from app.core.config import settings
from app.core.jwks_cache import prefetch_jwks
from app.core.logging import configure_logging, logger
from app.db.pool import close_pool, init_pool

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "starting",
        version="0.1.0",
        public_url=settings.public_url,
    )
    await init_pool()
    # Pré-charge le cache JWKS — best-effort (Keycloak peut être absent en dev)
    await prefetch_jwks()
    try:
        yield
    finally:
        await close_pool()
        logger.info("stopped")


app = FastAPI(
    title="Harpocrate",
    version="0.1.0",
    lifespan=lifespan,
)


# ─── Middleware : log des requêtes HTTP ───────────────────────────────────────
#
# RÈGLE DE SÉCURITÉ : les chemins /secrets ne doivent JAMAIS avoir leur body loggé.
# Ce middleware ne lit pas du tout le body ; il se contente de noter body_logged=False
# pour les chemins secrets afin de documenter explicitement l'intention.
# Les handlers eux-mêmes ne loguent jamais les champs encrypted_value.


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

app.include_router(health.router, prefix="/v1")
app.include_router(config_public.router, prefix="/v1")
app.include_router(config_keycloak.router, prefix="/v1")
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
