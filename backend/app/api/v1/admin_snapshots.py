"""Endpoints /v1/admin/snapshots/* — LOT_14."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.db.repositories import backups as backups_repo
from app.services import snapshot_scheduler as sched_svc
from app.services.gfs_rotation import GFSPolicy, GFSRetention
from app.services.audit import audit_log_insert

router = APIRouter(prefix="/admin/snapshots", tags=["admin-snapshots"])


def _policy_to_dict(policy: GFSPolicy) -> dict:
    return policy.to_dict()


def _snapshot_to_dict(r: backups_repo.BackupRecord) -> dict:
    return {
        "id": str(r.id),
        "filename": r.filename,
        "size_bytes": r.size_bytes,
        "created_at": r.created_at.isoformat(),
        "tier": r.tier,
        "description": r.description,
        "promoted_from_id": str(r.promoted_from_id) if r.promoted_from_id else None,
    }


@router.get("/policy")
async def get_policy(admin: AdminJwt) -> JSONResponse:
    """Retourne la politique de snapshot courante."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        policy = await sched_svc.get_policy(conn)
    return JSONResponse(_policy_to_dict(policy))


class RetentionBody(BaseModel):
    hourly: int = Field(default=24, ge=0)
    daily: int = Field(default=7, ge=0)
    weekly: int = Field(default=4, ge=0)
    monthly: int = Field(default=12, ge=0)
    yearly: int = Field(default=5, ge=0)


class PolicyBody(BaseModel):
    interval_minutes: int = Field(default=0, ge=0)
    retention: RetentionBody = Field(default_factory=RetentionBody)
    push_remote_after_snapshot: bool = False
    remote_destinations_to_push: list[str] = Field(default_factory=list)
    skip_if_no_change: bool = True

    def to_policy(self) -> GFSPolicy:
        return GFSPolicy(
            interval_minutes=self.interval_minutes,
            retention=GFSRetention(
                hourly=self.retention.hourly,
                daily=self.retention.daily,
                weekly=self.retention.weekly,
                monthly=self.retention.monthly,
                yearly=self.retention.yearly,
            ),
            push_remote_after_snapshot=self.push_remote_after_snapshot,
            remote_destinations_to_push=self.remote_destinations_to_push,
            skip_if_no_change=self.skip_if_no_change,
        )


@router.put("/policy")
async def update_policy(body: PolicyBody, admin: AdminJwt) -> JSONResponse:
    """Met à jour la politique et redémarre le scheduler."""
    if body.interval_minutes > 0 and body.interval_minutes < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_interval", "message": "interval_minutes must be 0 (disabled) or >= 5"},
        )
    policy = body.to_policy()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await sched_svc.set_policy(conn, policy)
        await audit_log_insert(
            conn, "admin.snapshot_policy_updated",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"interval_minutes": policy.interval_minutes},
        )

    scheduler = sched_svc.get_scheduler()
    await scheduler.restart()

    return JSONResponse(_policy_to_dict(policy))


class TriggerBody(BaseModel):
    force: bool = False
    skip_remote: bool = False
    description: str | None = None


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_snapshot(body: TriggerBody, admin: AdminJwt) -> JSONResponse:
    """Déclenche un snapshot immédiatement."""
    scheduler = sched_svc.get_scheduler()
    try:
        backup = await scheduler.trigger(
            force=body.force,
            skip_remote=body.skip_remote,
            description=body.description or "Manual snapshot",
        )
    except sched_svc._NoChangeError:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"skipped": True, "reason": "no_change"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "snapshot_failed", "message": str(exc)},
        ) from exc

    pool = await get_pool()
    async with pool.acquire() as conn:
        await audit_log_insert(
            conn, "admin.snapshot_triggered",
            actor_user_id=admin.user_id,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup.id), "force": body.force},
        )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"skipped": False, "snapshot": _snapshot_to_dict(backup)},
    )


@router.get("/history")
async def get_history(
    admin: AdminJwt,
    tier: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    """Liste l'historique des snapshots, filtrable par tier."""
    valid_tiers = {"hourly", "daily", "weekly", "monthly", "yearly"}
    if tier is not None and tier not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_tier", "message": f"tier must be one of {sorted(valid_tiers)}"},
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        snapshots = await backups_repo.list_snapshots(conn, tier=tier, limit=min(limit, 200))
    return JSONResponse({"snapshots": [_snapshot_to_dict(s) for s in snapshots]})
