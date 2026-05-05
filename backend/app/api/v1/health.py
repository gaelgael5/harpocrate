"""Endpoint /v1/health complet (LOT_21A, exigence E-5).

Checks :
- `db` : pool Postgres répond.
- `epoch_coherent` : epoch RAM >= epoch DB.
- `jwks_loaded` : au moins une clé JWKS chargée.
- `maintenance_active` : reflète l'état partagé.
- `last_sync_age_seconds` : âge du dernier refresh cluster (warning > 30s).

Statuts retournés :
- `ok` (200) : tout va bien.
- `degraded` (200) : warnings non bloquants (cluster sync en retard, JWKS vide…).
- `down` (503) : nœud à retirer du pool LB (DB inaccessible).
"""

from __future__ import annotations

import datetime
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.cluster_state import cluster_state
from app.core.config import settings
from app.core.jwks_cache import _keys as _jwks_keys
from app.db.pool import get_pool

router = APIRouter()

_VERSION = "0.1.0"
_STARTED_AT = time.monotonic()


def _uptime_seconds() -> float:
    return round(time.monotonic() - _STARTED_AT, 1)


@router.get("/health")
async def health() -> JSONResponse:
    checks: dict[str, object] = {}
    overall: str = "ok"

    # 1. DB
    db_epoch: int | None = None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            db_epoch_raw = await conn.fetchval(
                "SELECT epoch FROM server_session_epoch LIMIT 1"
            )
        checks["db"] = "ok"
        db_epoch = int(db_epoch_raw) if db_epoch_raw is not None else 0
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        overall = "down"

    # 2. Cohérence epoch
    if db_epoch is None:
        checks["epoch_coherent"] = False
    else:
        coherent = cluster_state.is_epoch_coherent(db_epoch)
        checks["epoch_coherent"] = coherent
        checks["db_epoch"] = db_epoch
        if not coherent and overall == "ok":
            overall = "degraded"

    # 3. JWKS chargé (la cache est un dict de kid → key)
    jwks_loaded = bool(_jwks_keys)
    checks["jwks_loaded"] = jwks_loaded
    if not jwks_loaded and overall == "ok":
        overall = "degraded"

    # 4. Maintenance
    checks["maintenance_active"] = cluster_state.maintenance_active

    # 5. Cluster sync — âge du dernier refresh
    if cluster_state.last_synced_at is not None:
        age = (
            datetime.datetime.now(datetime.UTC) - cluster_state.last_synced_at
        ).total_seconds()
        checks["last_sync_age_seconds"] = round(age, 2)
        if age > 30 and overall == "ok":
            overall = "degraded"
            checks["cluster_sync_warning"] = "Last sync > 30s ago"
    else:
        checks["last_sync_age_seconds"] = None

    status_code = 503 if overall == "down" else 200
    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "version": _VERSION,
            "instance_id": settings.instance_id,
            "uptime_seconds": _uptime_seconds(),
            "session_epoch": cluster_state.session_epoch,
            "checks": checks,
        },
    )
