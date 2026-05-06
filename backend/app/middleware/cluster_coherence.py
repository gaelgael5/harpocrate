"""Middleware de cohérence cluster (LOT_21A).

Avant chaque requête :
1. Si `maintenance_active=True` → 503, sauf endpoints exemptés (admin + health).
2. Si epoch RAM < epoch DB → 503 (le nœud est en retard, refuse de servir).

Cohérence stricte > performance : on lit l'epoch DB à chaque requête.
Le pool asyncpg rend cette lecture sub-milliseconde et garantit qu'aucune
requête ne sert sur un epoch périmé.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.cluster_state import cluster_state
from app.core.logging import logger
from app.db.pool import get_pool

_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/v1/health",
    "/v1/config/keycloak",
    "/v1/config/public",
})


def _is_exempt(path: str) -> bool:
    """Endpoints jamais bloqués : health + admin (pour gérer la sortie de maintenance)."""
    if path in _EXEMPT_PATHS:
        return True
    return path.startswith("/v1/admin/")


async def cluster_coherence_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Bloque les requêtes en mode maintenance ou si le nœud est désynchronisé."""
    path = request.url.path

    if _is_exempt(path):
        return await call_next(request)

    # 1. Maintenance globale (LOT 19, I-5)
    if cluster_state.maintenance_active:
        return JSONResponse(
            status_code=503,
            content={
                "error": "maintenance_in_progress",
                "reason": cluster_state.maintenance_reason,
                "estimated_end_at": (
                    cluster_state.maintenance_estimated_end_at.isoformat()
                    if cluster_state.maintenance_estimated_end_at
                    else None
                ),
            },
            headers={"Retry-After": "60"},
        )

    # 2. Cohérence epoch (LOT 19, I-3)
    # Si la sync cluster n'a jamais tourné (lifespan pas démarré : tests
    # unitaires qui montent l'app sans l'init complète), on bypass —
    # impossible de comparer un état non synchronisé.
    if cluster_state.last_synced_at is None:
        return await call_next(request)

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            db_epoch_raw = await conn.fetchval(
                "SELECT epoch FROM server_session_epoch LIMIT 1"
            )
    except Exception as exc:
        # Si on ne peut pas lire la DB, on laisse passer — l'endpoint
        # tombera lui-même en erreur, ce qui est plus parlant que 503 générique.
        logger.warning("cluster_middleware_db_read_failed", error=str(exc))
        return await call_next(request)

    db_epoch = int(db_epoch_raw) if db_epoch_raw is not None else 0
    if not cluster_state.is_epoch_coherent(db_epoch):
        logger.error(
            "node_epoch_incoherent_request_rejected",
            ram_epoch=cluster_state.session_epoch,
            db_epoch=db_epoch,
            path=path,
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "node_epoch_incoherent",
                "message": "This node is temporarily out of sync. Retry shortly.",
            },
            headers={"Retry-After": "5"},
        )

    return await call_next(request)
