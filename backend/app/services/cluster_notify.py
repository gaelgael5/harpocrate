"""Émission de NOTIFY Postgres pour propagation cluster (LOT_21A).

Quand un nœud modifie un état partagé (epoch, maintenance, JWKS), il émet
un `pg_notify` sur le canal correspondant. Tous les autres nœuds réagissent
en quasi-temps-réel via `app/core/cluster_sync.py`.

Règle d'or : émettre le NOTIFY DANS la même transaction que la modification.
Si la transaction rollback, le NOTIFY n'est pas émis — Postgres ne livre les
notifications qu'au COMMIT. Cela garantit qu'un nœud ne reçoit jamais une
notification pour un changement qui n'a pas eu lieu.
"""

from __future__ import annotations

import datetime
import json

import asyncpg

from app.core.config import settings

CHANNEL_EPOCH = "harpocrate_epoch_changed"
CHANNEL_MAINTENANCE = "harpocrate_maintenance_changed"
CHANNEL_JWKS = "harpocrate_jwks_invalidated"


def _payload(event: str, **extra: object) -> str:
    body: dict[str, object] = {
        "event": event,
        "emitted_by": settings.instance_id,
        "emitted_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    body.update(extra)
    return json.dumps(body)


async def notify_epoch_changed(
    conn: asyncpg.Connection[asyncpg.Record],
    new_epoch: int,
) -> None:
    """Notifie le cluster qu'un nouvel epoch a été émis (post-restore typiquement)."""
    await conn.execute(
        f"SELECT pg_notify('{CHANNEL_EPOCH}', $1)",
        _payload("epoch_changed", new_value=new_epoch),
    )


async def notify_maintenance_changed(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    active: bool,
) -> None:
    """Notifie le cluster d'une bascule du mode maintenance."""
    await conn.execute(
        f"SELECT pg_notify('{CHANNEL_MAINTENANCE}', $1)",
        _payload("maintenance_changed", active=active),
    )


async def notify_jwks_invalidated(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Notifie le cluster qu'un refresh JWKS est nécessaire."""
    await conn.execute(
        f"SELECT pg_notify('{CHANNEL_JWKS}', $1)",
        _payload("jwks_invalidated"),
    )
