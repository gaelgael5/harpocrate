"""Lock global partagé entre les workers de backup.

Pourquoi : `pg_dump` consomme CPU + IO + RAM sur la base. Si deux workers
(snapshot scheduler et scheduled_backups scheduler) déclenchent un dump
simultanément, on double la charge sans bénéfice et on peut faire échouer
des requêtes utilisateurs (timeouts, contention disque).

Ce module expose un `asyncio.Lock` unique au process, acquis par les deux
workers autour de leur création de backup. Si le snapshot tourne, le
scheduled_backups attend (et inverse).

Note : intra-process uniquement. Pour un déploiement multi-instance, il
faudra un advisory lock Postgres (`pg_try_advisory_lock`) — pas dans ce LOT.
"""

from __future__ import annotations

import asyncio


_lock: asyncio.Lock | None = None


def get_global_backup_lock() -> asyncio.Lock:
    """Retourne le lock global. Crée à la première demande (lazy).

    Doit être appelé depuis le contexte d'une boucle asyncio (sinon
    asyncio.Lock() lève une RuntimeError).
    """
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock
