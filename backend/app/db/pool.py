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
        # `effective_db_dsn` applique le password override si présent
        # (cf. db_password_override_path — utilisé après un pairing standby).
        _pool = await asyncpg.create_pool(
            dsn=settings.effective_db_dsn,
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


async def refresh_pool() -> asyncpg.Pool[asyncpg.Record]:
    """Close the current pool (if any) and re-init with current settings.

    Utilisé après pairing standby : le step 6 du wizard écrit le password
    override file, donc `settings.effective_db_dsn` retourne maintenant un DSN
    différent. Sans refresh, le pool en mémoire continue à utiliser l'ancien
    password et le backend tombe en 503 jusqu'à un restart manuel du process.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db_pool_closed_for_refresh")
    return await init_pool()


async def get_pool() -> asyncpg.Pool:
    """Return the initialized pool or raise RuntimeError if not initialized."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
