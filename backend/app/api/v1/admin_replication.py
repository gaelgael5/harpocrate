"""Endpoints /v1/admin/replication/* — LOT_20 + LOT réplication itération 1.

Auth : AdminJwt uniquement.

- GET /strategies — liste les stratégies disponibles + actives
- POST /strategies/{id}/activate — active une stratégie (multi-actives OK)
- POST /strategies/{id}/deactivate — désactive sans toucher aux autres
- GET /status — état temps réel (interroge Patroni si stratégie patroni)
- GET /streaming/nodes — liste les standby (avec last_state/last_lag)
- POST /streaming/nodes — ajoute un standby, retourne le bundle de config
- DELETE /streaming/nodes/{id} — supprime un standby (DROP ROLE + delete row)
- POST /streaming/reload-pg-hba — reload pg_hba.conf après modif manuelle
"""

from __future__ import annotations

from datetime import UTC
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.db.repositories import replication_strategies as strat_repo
from app.db.repositories import system_metadata as meta_repo
from app.services import replication as svc
from app.services import streaming_replication as streaming_svc

router = APIRouter(prefix="/admin/replication", tags=["admin-replication"])


@router.get("/strategies", response_class=JSONResponse)
async def list_strategies(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await strat_repo.list_strategies(conn)
    return JSONResponse(
        {
            "strategies": [svc.row_to_dict(r) for r in rows],
        }
    )


@router.post(
    "/strategies/{strategy_id}/activate",
    status_code=status.HTTP_200_OK,
    response_class=JSONResponse,
)
async def activate_strategy(strategy_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Active une stratégie. Plusieurs stratégies peuvent être actives en
    parallèle (depuis la migration 026)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        ok = await svc.activate(conn, strategy_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "strategy_not_found_or_disabled"},
        )
    return JSONResponse({"activated": True, "strategy_id": str(strategy_id)})


@router.post(
    "/strategies/{strategy_id}/deactivate",
    status_code=status.HTTP_200_OK,
    response_class=JSONResponse,
)
async def deactivate_strategy(strategy_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Désactive une stratégie sans toucher aux autres."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        ok = await svc.deactivate(conn, strategy_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "strategy_not_found_or_already_inactive"},
        )
    return JSONResponse({"deactivated": True, "strategy_id": str(strategy_id)})


# ─── Streaming async — gestion des standby nodes ────────────────────────────


class AddNodeRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    role: str = Field(default="standby_ro")
    notes: str | None = Field(default=None, max_length=2000)
    # Adresse du master telle que vue depuis le standby (peut être différente
    # de ce que voit Harpocrate, ex: IP LAN vs hostname public).
    master_host: str = Field(min_length=1, max_length=255)
    master_port: int = Field(default=5432, ge=1, le=65535)
    standby_data_dir: str = Field(default="/var/lib/postgresql/16/main", max_length=512)


@router.get("/streaming/nodes", response_class=JSONResponse)
async def list_streaming_nodes(admin: AdminJwt) -> JSONResponse:
    """Liste tous les standby (toutes stratégies streaming_async confondues)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        nodes = await streaming_svc.list_nodes(conn)
    return JSONResponse({"nodes": [n.to_dict() for n in nodes]})


@router.post(
    "/streaming/nodes",
    status_code=status.HTTP_201_CREATED,
    response_class=JSONResponse,
)
async def add_streaming_node(body: AddNodeRequest, admin: AdminJwt) -> JSONResponse:
    """Ajoute un standby et retourne le bundle de config (1 fois — le password
    n'est plus jamais ré-affichable après cette réponse)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # On rattache le node à la stratégie streaming_async (la seule pour
        # cette itération). Si elle n'existe pas, on remonte une erreur claire.
        strat = await conn.fetchrow(
            "SELECT id FROM replication_strategies WHERE type = 'streaming_async' LIMIT 1"
        )
        if strat is None:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={
                    "error": "streaming_strategy_missing",
                    "message": "streaming_async strategy not seeded. Run migration 026.",
                },
            )

        try:
            node_id, bundle = await streaming_svc.add_node(
                conn,
                strategy_id=strat["id"],
                label=body.label,
                host=body.host,
                port=body.port,
                role=body.role,
                notes=body.notes,
                master_host=body.master_host,
                master_port=body.master_port,
                standby_data_dir=body.standby_data_dir,
                created_by_user_id=admin.user_id,
            )
        except Exception as exc:
            msg = str(exc)
            if "unique" in msg.lower() or "23505" in msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "label_or_app_name_already_exists"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": msg},
            ) from exc

    payload: dict[str, Any] = {
        "id": str(node_id),
        "bundle": bundle.to_dict(),
    }
    return JSONResponse(payload, status_code=status.HTTP_201_CREATED)


@router.delete(
    "/streaming/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_streaming_node(node_id: UUID, admin: AdminJwt) -> Response:
    """Supprime un standby : DROP ROLE côté master + DELETE row.

    Si le DROP ROLE échoue (ex: standby encore connecté), on remonte 409
    pour que l'admin déconnecte le standby d'abord.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            ok = await streaming_svc.delete_node(conn, node_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "drop_role_failed",
                    "message": str(exc),
                },
            ) from exc
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "node_not_found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/streaming/postgres-info", response_class=JSONResponse)
async def get_postgres_info(admin: AdminJwt) -> JSONResponse:
    """Expose les paramètres Postgres de l'instance courante (master) :
    version, paths config/data/hba, wal_level, max_wal_senders, etc.

    Utilisé par l'UI Réplication pour aider l'admin à configurer un standby :
    il peut lire ces valeurs côté master et copier les bons paramètres dans
    la config standby (postgresql.conf, primary_conninfo, etc.).

    Lecture seule, aucun side-effect.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        info = await streaming_svc.get_postgres_info(conn)
    return JSONResponse(info.to_dict())


@router.post("/streaming/reload-pg-hba", response_class=JSONResponse)
async def reload_pg_hba(admin: AdminJwt) -> JSONResponse:
    """À appeler après que l'admin a modifié pg_hba.conf manuellement côté
    master. Lance `SELECT pg_reload_conf()` pour que les nouvelles règles
    prennent effet sans redémarrer Postgres."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await streaming_svc.reload_pg_hba(conn)
    return JSONResponse({"reloaded": True})


# ─── (it2) test-connect / observations / lag-thresholds ────────────────────


@router.post("/streaming/nodes/{node_id}/test-connect", response_class=JSONResponse)
async def test_node_connect(node_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Ping TCP du standby host:port. Pas d'auth Postgres testée (le
    password de réplication n'est pas stocké côté Harpocrate).

    Retourne 200 systématique (le résultat ok/ko est dans le body) — même
    logique que les test connect remote backups, pour ne pas se faire avaler
    par un reverse-proxy qui transformerait un 5xx en page d'erreur générique.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await streaming_svc.test_node_connect(conn, node_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "node_not_found"},
        )
    return JSONResponse(result.to_dict())


@router.get("/streaming/nodes/{node_id}/observations", response_class=JSONResponse)
async def list_node_observations(
    node_id: UUID,
    admin: AdminJwt,
    hours: int = 24,
) -> JSONResponse:
    """Historique des observations d'un node sur les `hours` dernières heures
    (max 168 = 7 jours, la rétention de la table)."""
    from datetime import datetime, timedelta

    if hours <= 0 or hours > 168:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "hours must be in (0, 168]"},
        )
    since = datetime.now(UTC) - timedelta(hours=hours)
    pool = await get_pool()
    async with pool.acquire() as conn:
        node = await streaming_svc.get_node(conn, node_id)
        if node is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "node_not_found"},
            )
        rows = await streaming_svc.list_observations(conn, node_id=node_id, since=since)
    return JSONResponse(
        {
            "node": node.to_dict(),
            "observations": [
                {
                    "observed_at": r["observed_at"].isoformat(),
                    "state": r["state"],
                    "lag_bytes": r["lag_bytes"],
                }
                for r in rows
            ],
        }
    )


class LagThresholdsBody(BaseModel):
    warning_bytes: int = Field(ge=0)
    critical_bytes: int = Field(ge=0)


@router.get("/streaming/lag-thresholds", response_class=JSONResponse)
async def get_lag_thresholds(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        thresholds = await streaming_svc.get_lag_thresholds(conn)
    return JSONResponse(thresholds.to_dict())


@router.patch("/streaming/lag-thresholds", response_class=JSONResponse)
async def set_lag_thresholds(body: LagThresholdsBody, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new = await streaming_svc.set_lag_thresholds(
                conn,
                warning_bytes=body.warning_bytes,
                critical_bytes=body.critical_bytes,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_thresholds", "message": str(exc)},
            ) from exc
    return JSONResponse(new.to_dict())


@router.get("/self-info", response_class=JSONResponse)
async def get_self_info(admin: AdminJwt) -> JSONResponse:
    """Retourne les infos publiques à transmettre au pair lors d'un appairage :
    URL publique du backend Harpocrate, hostname extrait, port Postgres annoncé.
    """
    from urllib.parse import urlparse

    from app.core.config import settings

    public_url = settings.public_url
    hostname = urlparse(public_url).hostname or ""
    return JSONResponse(
        {
            "public_url": public_url,
            "advertised_pg_host": hostname,
            "advertised_pg_port": settings.replication_advertised_pg_port,
        }
    )


@router.get("/standby-of", response_class=JSONResponse)
async def get_standby_of(admin: AdminJwt) -> JSONResponse:
    """Retourne l'URL du master si cette instance est asservie, sinon None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        value = await meta_repo.get_value(conn, "replication.is_standby_of")
    return JSONResponse({"is_standby_of": value})


# ─── Failover MVP — promotion manuelle du standby ────────────────────────────


class CanPromoteResponse(BaseModel):
    """Lecture : indique si cette instance peut être promue en master."""

    can_promote: bool
    current_role: str  # "standby" | "master" | "standalone"
    master_url: str | None = None
    reason_if_not: str | None = None


class PromoteRequest(BaseModel):
    """Body POST /promote — exige les 2 confirmations admin.

    Double check-box anti-erreur (split-brain) : l'admin DOIT confirmer
    explicitement qu'il a coupé l'ancien master ET qu'il reconfigurera les
    clients vers ce nouveau master.
    """

    confirm_master_down: bool = Field(
        ..., description="L'admin confirme que l'ancien master est arrêté."
    )
    confirm_clients_will_be_reconfigured: bool = Field(
        ...,
        description="L'admin confirme qu'il reconfigurera les clients après promotion.",
    )


class PromoteResponse(BaseModel):
    promoted: bool
    old_master_url: str | None = None


@router.get("/can-promote", response_model=CanPromoteResponse)
async def can_promote_endpoint(admin: AdminJwt) -> CanPromoteResponse:
    """Indique si cette instance est promouvable (standby en recovery).

    Utilisé par l'UI pour afficher/masquer le bouton 'Promouvoir en master'.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        elig = await streaming_svc.get_promote_eligibility(conn)
    return CanPromoteResponse(
        can_promote=elig.can_promote,
        current_role=elig.current_role,
        master_url=elig.master_url,
        reason_if_not=elig.reason_if_not,
    )


@router.post(
    "/promote",
    response_model=PromoteResponse,
    status_code=status.HTTP_200_OK,
)
async def promote_endpoint(
    req: PromoteRequest,
    admin: AdminJwt,
) -> PromoteResponse:
    """Promeut le standby local en master via pg_promote().

    Exige les 2 confirmations admin (`confirm_master_down` +
    `confirm_clients_will_be_reconfigured`). Si l'une des deux est False
    → 400 `missing_confirmation`. Si l'instance n'est pas en mode standby
    → 409 `not_in_standby_mode`. Si pg_promote échoue à sortir du recovery
    → 500 `promotion_failed`.
    """
    if not (req.confirm_master_down and req.confirm_clients_will_be_reconfigured):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_confirmation"},
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await streaming_svc.promote_standby_to_master(
                conn,
                actor_user_id=admin.user_id,
            )
        except streaming_svc.NotInStandbyModeError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "not_in_standby_mode"},
            ) from None
        except streaming_svc.PromotionFailedError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "promotion_failed", "cause": str(e)},
            ) from e
    return PromoteResponse(
        promoted=result.promoted,
        old_master_url=result.old_master_url,
    )


@router.get("/status", response_class=JSONResponse)
async def replication_status(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        active = await svc.get_active(conn)
    if active is None:
        return JSONResponse({"strategy": None, "status": "no_active_strategy"})

    row, strategy = active
    live_status = await strategy.get_status()
    return JSONResponse(
        {
            "strategy": svc.row_to_dict(row),
            "live": live_status,
        }
    )
