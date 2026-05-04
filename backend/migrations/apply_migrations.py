"""Apply pending SQL migrations to the database.

Usage: python -m migrations.apply_migrations
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import asyncpg

from app.core.config import settings

_log = logging.getLogger(__name__)


def _migrations_dir() -> Path:
    return Path(__file__).parent


async def apply_migrations() -> None:
    conn = await asyncpg.connect(dsn=settings.db_dsn)
    try:
        bootstrap = (_migrations_dir() / "000_migrations_table.sql").read_text()
        await conn.execute(bootstrap)

        applied = {
            row["filename"]: row["checksum"]
            for row in await conn.fetch(
                "SELECT filename, checksum FROM _migrations"
            )
        }

        files = sorted(
            f
            for f in _migrations_dir().glob("*.sql")
            if f.name != "000_migrations_table.sql"
        )

        for migration in files:
            content = migration.read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()

            if migration.name in applied:
                if applied[migration.name] != checksum:
                    raise RuntimeError(
                        f"Migration {migration.name} checksum mismatch — "
                        f"manual review required"
                    )
                continue

            _log.info("migration_applying", extra={"migration": migration.name})
            async with conn.transaction():
                await conn.execute(content)
                await conn.execute(
                    "INSERT INTO _migrations (filename, checksum) "
                    "VALUES ($1, $2)",
                    migration.name,
                    checksum,
                )
            _log.info("migration_applied", extra={"migration": migration.name})

        _log.info("migrations_up_to_date")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(apply_migrations())
