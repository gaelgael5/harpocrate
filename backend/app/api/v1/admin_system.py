"""Endpoints /v1/admin/system/* — LOT_12C/12E + LOT_56 (age-keygen).

GET  /v1/admin/system/info       — stats système (users, wallets, secrets, backups)
GET  /v1/admin/system/env        — config env (sensibles redactés)
POST /v1/admin/system/age-keygen — génère une paire AGE pour les backups
GET  /v1/admin/users             — liste tous les utilisateurs
GET  /v1/admin/audit-log         — journal d'audit global (sans filtrage par user)
"""
from __future__ import annotations

import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.db.repositories import audit_log as audit_log_repo
from app.services.age_keygen import (
    AgeKeygenError,
    generate_age_keypair,
    store_age_public_key,
)

router = APIRouter(prefix="/admin", tags=["admin-system"])


# ─── GET /v1/admin/system/info ────────────────────────────────────────────────


@router.get("/system/info")
async def get_system_info(admin: AdminJwt) -> JSONResponse:
    """Retourne les compteurs système. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        bootstrapped_count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE rsa_public_key IS NOT NULL"
        )
        wallets_count = await conn.fetchval("SELECT COUNT(*) FROM wallets")
        secrets_count = await conn.fetchval("SELECT COUNT(*) FROM secrets")
        api_keys_count = await conn.fetchval(
            "SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL"
        )
        backups_count = await conn.fetchval("SELECT COUNT(*) FROM backups_local")
        audit_events_count = await conn.fetchval("SELECT COUNT(*) FROM audit_log")

    return JSONResponse(
        {
            "users_count": users_count,
            "bootstrapped_users_count": bootstrapped_count,
            "wallets_count": wallets_count,
            "secrets_count": secrets_count,
            "active_api_keys_count": api_keys_count,
            "backups_count": backups_count,
            "audit_events_count": audit_events_count,
        }
    )


# ─── GET /v1/admin/system/env ────────────────────────────────────────────────


@router.get("/system/env")
async def get_env_config(admin: AdminJwt) -> JSONResponse:
    """Retourne la configuration env (champs sensibles redactés). Requiert rôle admin."""
    non_sensitive = settings.get_non_sensitive_fields()
    sensitive_names = [
        f"HARPOCRATE_{name.upper()}" for name in settings.get_sensitive_fields()
    ]

    env_vars: dict[str, str] = {}
    for key, value in non_sensitive.items():
        env_vars[key] = str(value)
    for key in sensitive_names:
        env_vars[key] = "[REDACTED]"

    return JSONResponse(
        {
            "env": dict(sorted(env_vars.items())),
            "sensitive_keys": sorted(sensitive_names),
        }
    )


# ─── POST /v1/admin/system/age-keygen ────────────────────────────────────────


@router.post("/system/age-keygen")
async def age_keygen(admin: AdminJwt) -> JSONResponse:
    """Génère une paire AGE pour les backups (LOT_56).

    La clé PUBLIQUE est immédiatement stockée en DB (system_metadata) et
    utilisée par les prochains create_backup — pas besoin de redémarrer.

    La clé PRIVÉE est retournée UNE SEULE FOIS dans la réponse, JAMAIS
    persistée côté serveur (zero-knowledge). L'admin DOIT la stocker dans
    un endroit sûr (gestionnaire de mdp, coffre). Sans elle, AUCUN backup
    ne peut être restauré.
    """
    try:
        public_key, private_key = await generate_age_keypair()
    except AgeKeygenError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "age_keygen_failed", "message": str(exc)},
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "error": "age_binary_missing",
                "message": "The 'age' binary is not installed on the backend container",
            },
        ) from exc

    # Persiste immédiatement la clé publique en DB → applicable sans restart.
    pool = await get_pool()
    async with pool.acquire() as conn:
        await store_age_public_key(conn, public_key)

    return JSONResponse(
        {
            "public_key": public_key,
            "private_key": private_key,
            "applied": True,
            "warning": (
                "The private key is shown ONLY ONCE. Save it in a password "
                "manager NOW — without it, no backup can be restored."
            ),
        }
    )


# ─── GET /v1/admin/users ─────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    admin: AdminJwt,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """Retourne la liste de tous les utilisateurs. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, email, display_name, created_at, last_unlock_at,
                quarantine_until, disabled_at,
                (rsa_public_key IS NOT NULL) AS has_bootstrap
            FROM users
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM users")

    users = [
        {
            "id": str(r["id"]),
            "email": r["email"],
            "display_name": r["display_name"],
            "created_at": r["created_at"].isoformat(),
            "last_unlock_at": r["last_unlock_at"].isoformat() if r["last_unlock_at"] else None,
            "has_bootstrap": r["has_bootstrap"],
            "quarantine_until": r["quarantine_until"].isoformat() if r["quarantine_until"] else None,
            "disabled_at": r["disabled_at"].isoformat() if r["disabled_at"] else None,
        }
        for r in rows
    ]

    return JSONResponse({"users": users, "total": total})


# ─── GET /v1/admin/audit-log ──────────────────────────────────────────────────


@router.get("/audit-log")
async def admin_audit_log(
    admin: AdminJwt,
    action: str | None = Query(default=None),
    action_prefix: str | None = Query(default=None),
    since: datetime.datetime | None = Query(default=None),
    until: datetime.datetime | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
    actor_api_key_id: UUID | None = Query(default=None),
    success: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
    """Journal d'audit global (toutes actions, tous acteurs). Requiert rôle admin."""
    cursor_at: datetime.datetime | None = None
    cursor_id: int | None = None
    if cursor:
        try:
            cursor_at, cursor_id = audit_log_repo.decode_cursor(cursor)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_cursor", "message": "Invalid pagination cursor"},
            )

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await audit_log_repo.query_audit_log(
            conn,
            # Pas de contrainte de sécurité = accès global admin
            force_actor_api_key_id=None,
            jwt_user_id=None,
            jwt_owned_wallet_ids=None,
            filter_action=action,
            filter_action_prefix=action_prefix,
            filter_since=since,
            filter_until=until,
            filter_actor_user_id=actor_user_id,
            filter_actor_api_key_id=actor_api_key_id,
            filter_target_secret_id=None,
            filter_success=success,
            cursor_occurred_at=cursor_at,
            cursor_id=cursor_id,
            limit=limit,
        )

    has_more = len(rows) > limit
    page = rows[:limit]

    events = []
    for r in page:
        events.append(
            {
                "id": r["id"],
                "action": r["action"],
                "occurred_at": r["occurred_at"].isoformat(),
                "success": r["success"],
                "actor": {
                    "type": "api_key" if r["actor_api_key_id"] else "user",
                    "id": str(r["actor_api_key_id"] or r["actor_user_id"] or ""),
                    "email": r.get("actor_email"),
                    "display_name": r.get("actor_display_name"),
                    "name": r.get("actor_api_key_name"),
                    "ip": r.get("actor_ip"),
                },
                "target": {
                    "wallet_id": str(r["target_wallet_id"]) if r["target_wallet_id"] else None,
                    "wallet_name": r.get("target_wallet_name"),
                    "secret_id": str(r["target_secret_id"]) if r["target_secret_id"] else None,
                },
            }
        )

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = audit_log_repo.encode_cursor(last["occurred_at"], last["id"])

    return JSONResponse({"events": events, "next_cursor": next_cursor})
