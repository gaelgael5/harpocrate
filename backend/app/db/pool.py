"""Pool asyncpg — initialisé dans le lifespan FastAPI (cf app/main.py)."""

from __future__ import annotations

import asyncpg

from app.core.config import settings
from app.core.logging import logger

_pool: asyncpg.Pool[asyncpg.Record] | None = None


async def init_pool() -> asyncpg.Pool[asyncpg.Record]:
    """Initialize asyncpg pool if not already initialized (idempotent)."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.db_dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("db_pool_initialized")
    return _pool


async def close_pool() -> None:
    """Close asyncpg pool and clear global state."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db_pool_closed")


async def get_pool() -> asyncpg.Pool:
    """Return the initialized pool or raise RuntimeError if not initialized."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
