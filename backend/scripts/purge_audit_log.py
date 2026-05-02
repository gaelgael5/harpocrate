"""Purge des audit logs au-delà de la rétention configurée.

Usage:
    python scripts/purge_audit_log.py [--dry-run]

À lancer via cron (exemple) :
    0 3 * * * cd /app && python scripts/purge_audit_log.py >> /var/log/harpocrate-purge.log 2>&1

Le script supprime par batch de 10 000 lignes pour éviter les longues transactions
et les locks trop importants sur la table audit_log.

La rétention est configurée via HARPOCRATE_AUDIT_RETENTION_DAYS (défaut : 90 jours).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

from app.core.config import settings
from app.core.logging import configure_logging, logger

_BATCH_SIZE = 10_000


async def purge(*, dry_run: bool = False) -> int:
    """Supprime les événements d'audit plus vieux que audit_retention_days.

    Retourne le nombre total de lignes supprimées (0 si dry_run).
    """
    configure_logging()

    retention_days = settings.audit_retention_days
    logger.info(
        "audit_purge_start",
        retention_days=retention_days,
        dry_run=dry_run,
    )

    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(
        dsn=settings.db_dsn
    )
    try:
        count: int = await conn.fetchval(
            "SELECT COUNT(*) FROM audit_log WHERE occurred_at < NOW() - $1::interval",
            f"{retention_days} days",
        )

        logger.info(
            "audit_purge_target",
            count=count,
            dry_run=dry_run,
        )

        if dry_run or count == 0:
            if count == 0:
                logger.info("audit_purge_nothing_to_delete")
            return 0

        deleted_total = 0
        iteration = 0

        while True:
            iteration += 1
            result: str = await conn.execute(
                """
                DELETE FROM audit_log
                WHERE id IN (
                    SELECT id FROM audit_log
                    WHERE occurred_at < NOW() - $1::interval
                    ORDER BY occurred_at ASC
                    LIMIT $2
                )
                """,
                f"{retention_days} days",
                _BATCH_SIZE,
            )
            # asyncpg retourne "DELETE N" — on extrait N
            batch_deleted = int(result.split()[-1])
            deleted_total += batch_deleted

            logger.info(
                "audit_purge_batch",
                iteration=iteration,
                batch_deleted=batch_deleted,
                total_deleted=deleted_total,
            )

            if batch_deleted < _BATCH_SIZE:
                break

        logger.info(
            "audit_purge_complete",
            total_deleted=deleted_total,
        )
        return deleted_total

    finally:
        await conn.close()


def main() -> None:
    """Point d'entrée CLI."""
    parser = argparse.ArgumentParser(
        description="Purge des audit logs Harpocrate au-delà de la rétention.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le nombre de lignes à supprimer sans les supprimer.",
    )
    args = parser.parse_args()

    deleted = asyncio.run(purge(dry_run=args.dry_run))

    if args.dry_run:
        print(f"[dry-run] {deleted} lignes supprimées (simulation).")
    else:
        print(f"Purge terminée : {deleted} lignes supprimées.")

    sys.exit(0)


if __name__ == "__main__":
    main()
