"""FastAPI app — lifespan gère le pool asyncpg et le cache JWKS."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import auth, config_keycloak, config_public, health
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

app.include_router(health.router, prefix="/v1")
app.include_router(config_public.router, prefix="/v1")
app.include_router(config_keycloak.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
