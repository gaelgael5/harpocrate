"""Endpoints admin pour la gestion des utilisateurs — Lot 4A.

Couvre les opérations admin sur les comptes utilisateurs identifiées dans
l'audit (features A-2 → A-5) :

- POST   /v1/admin/users/{user_id}/disable           — A-2 : disable un compte
- POST   /v1/admin/users/{user_id}/enable            — A-2 : reactive un compte
- POST   /v1/admin/users/{user_id}/quarantine/clear  — A-3 : leve la quarantaine
- PATCH  /v1/admin/users/{user_id}/force-reverify-next-login — A-4 : flag re-verif
- DELETE /v1/admin/users/{user_id}/identities/{identity_id}  — A-5 : delie une identite

Tous les endpoints requierent le role admin (dependance `AdminJwt`) et
emettent une ligne audit_log avec `actor_user_id = admin.user_id` et
`target_user_id = <user_id>`.

Effet de bord cote enforcement :
- `disabled_at IS NOT NULL` : le user ne peut plus s'authentifier (check
  ajoute dans `app/core/security.py::require_jwt_user_with_enforcement`).
- `quarantine_until` au futur : self-service via `/me/quarantine/exit`,
  ou clear admin via cet endpoint.
- `force_reverify_next_login = TRUE` : le prochain login force la
  re-saisie du JWT/passphrase (lu par le frontend).
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.services.audit import audit_log_insert

router = APIRouter(prefix="/admin", tags=["admin-users"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _ensure_user_exists(
    conn: asyncpg.Connection[asyncpg.Record], user_id: UUID
) -> None:
    """Verifie que le user existe (et n'est pas un user systeme)."""
    exists = await conn.fetchval(
        "SELECT 1 FROM users WHERE id = $1 AND is_system = FALSE",
        user_id,
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found", "message": "User not found"},
        )


# ─── A-2 : POST /v1/admin/users/{user_id}/disable ────────────────────────────


class DisableBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/users/{user_id}/disable", status_code=status.HTTP_200_OK)
async def disable_user(
    user_id: UUID,
    body: DisableBody,
    admin: AdminJwt,
    request: Request,
) -> JSONResponse:
    """Disable un compte utilisateur (A-2).

    Effet :
    - `disabled_at = NOW()`, `disabled_reason = body.reason`
    - Le user ne peut plus s'authentifier sur les endpoints proteges par
      `JwtUser` (cf. enforcement dans `core/security.py`).
    - Les API keys du user continuent de fonctionner tant qu'elles ne sont
      pas explicitement revoquees — choix volontaire pour permettre une
      remediation progressive (la revocation en masse est un endpoint a part).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_user_exists(conn, user_id)
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE users
                   SET disabled_at = NOW(),
                       disabled_reason = $2
                 WHERE id = $1
                """,
                user_id,
                body.reason,
            )
            await audit_log_insert(
                conn,
                "admin.user_disabled",
                actor_user_id=admin.user_id,
                actor_ip=_client_ip(request),
                target_user_id=user_id,
                metadata={"reason": body.reason},
            )
    return JSONResponse({"status": "disabled", "user_id": str(user_id)})


# ─── A-2 : POST /v1/admin/users/{user_id}/enable ─────────────────────────────


@router.post("/users/{user_id}/enable", status_code=status.HTTP_200_OK)
async def enable_user(
    user_id: UUID,
    admin: AdminJwt,
    request: Request,
) -> JSONResponse:
    """Reactive un compte utilisateur (A-2).

    Effet : `disabled_at = NULL`, `disabled_reason = NULL`.
    Si l'utilisateur etait en quarantaine, la quarantaine n'est PAS levee
    automatiquement (action distincte via `/quarantine/clear`).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_user_exists(conn, user_id)
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE users
                   SET disabled_at = NULL,
                       disabled_reason = NULL
                 WHERE id = $1
                """,
                user_id,
            )
            await audit_log_insert(
                conn,
                "admin.user_enabled",
                actor_user_id=admin.user_id,
                actor_ip=_client_ip(request),
                target_user_id=user_id,
            )
    return JSONResponse({"status": "enabled", "user_id": str(user_id)})


# ─── A-3 : POST /v1/admin/users/{user_id}/quarantine/clear ──────────────────


@router.post("/users/{user_id}/quarantine/clear", status_code=status.HTTP_200_OK)
async def clear_quarantine(
    user_id: UUID,
    admin: AdminJwt,
    request: Request,
) -> JSONResponse:
    """Leve la quarantaine d'un utilisateur (A-3).

    Effet : `quarantine_until = NULL`, `quarantine_reason = NULL`.

    A utiliser apres verification d'identite hors-bande quand le user
    legitime ne peut pas declencher le self-service `/me/quarantine/exit`
    (ex: a perdu sa passphrase ET sa phrase de recuperation, ou le mail
    Listmonk ne part pas). N'est pas a banaliser : noter dans le ticket
    interne quelle verification a ete faite.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_user_exists(conn, user_id)
        async with conn.transaction():
            previous = await conn.fetchrow(
                "SELECT quarantine_until, quarantine_reason FROM users WHERE id = $1",
                user_id,
            )
            await conn.execute(
                """
                UPDATE users
                   SET quarantine_until = NULL,
                       quarantine_reason = NULL
                 WHERE id = $1
                """,
                user_id,
            )
            await audit_log_insert(
                conn,
                "admin.user_quarantine_cleared",
                actor_user_id=admin.user_id,
                actor_ip=_client_ip(request),
                target_user_id=user_id,
                metadata={
                    "previous_until": (
                        previous["quarantine_until"].isoformat()
                        if previous and previous["quarantine_until"]
                        else None
                    ),
                    "previous_reason": (
                        previous["quarantine_reason"] if previous else None
                    ),
                },
            )
    return JSONResponse({"status": "quarantine_cleared", "user_id": str(user_id)})


# ─── A-4 : PATCH /v1/admin/users/{user_id}/force-reverify-next-login ────────


class ForceReverifyBody(BaseModel):
    enabled: bool


@router.patch(
    "/users/{user_id}/force-reverify-next-login",
    status_code=status.HTTP_200_OK,
)
async def set_force_reverify(
    user_id: UUID,
    body: ForceReverifyBody,
    admin: AdminJwt,
    request: Request,
) -> JSONResponse:
    """Active/desactive le flag `force_reverify_next_login` (A-4).

    Quand `enabled=true`, le prochain login du user impose une re-saisie
    complete (JWT + passphrase) — utilise apres une suspicion d'incident
    ou un changement d'organisation. Le flag est consomme automatiquement
    a la prochaine validation (cf. service `identity_governance`).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_user_exists(conn, user_id)
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE users
                   SET force_reverify_next_login = $2
                 WHERE id = $1
                """,
                user_id,
                body.enabled,
            )
            await audit_log_insert(
                conn,
                "admin.user_force_reverify_set" if body.enabled
                else "admin.user_force_reverify_cleared",
                actor_user_id=admin.user_id,
                actor_ip=_client_ip(request),
                target_user_id=user_id,
                metadata={"enabled": body.enabled},
            )
    return JSONResponse(
        {
            "user_id": str(user_id),
            "force_reverify_next_login": body.enabled,
        }
    )


# ─── A-5 : DELETE /v1/admin/users/{user_id}/identities/{identity_id} ────────


@router.delete(
    "/users/{user_id}/identities/{identity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_unlink_identity(
    user_id: UUID,
    identity_id: UUID,
    admin: AdminJwt,
    request: Request,
) -> JSONResponse:
    """Delie une identite OIDC d'un utilisateur (A-5).

    Effet : supprime la ligne `user_external_identities` ciblee. Le
    user_external_identities row doit appartenir au user_id (verification
    via clause WHERE).

    Refuse de delier la derniere identite — un user sans identite OIDC ne
    peut plus se connecter via Keycloak (l'auth admin locale reste
    accessible si configuree, mais ne s'applique pas a un user OIDC normal).

    Endpoint distinct du self-service `DELETE /me/identities/{id}` qui
    n'autorise que le user a delier ses propres identites.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_user_exists(conn, user_id)

        identity_row = await conn.fetchrow(
            """
            SELECT provider, external_subject
              FROM user_external_identities
             WHERE id = $1 AND user_id = $2
            """,
            identity_id,
            user_id,
        )
        if identity_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "identity_not_found",
                    "message": "Identity not found for this user",
                },
            )

        remaining = await conn.fetchval(
            "SELECT COUNT(*) FROM user_external_identities WHERE user_id = $1",
            user_id,
        )
        if remaining <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "last_identity_cannot_be_unlinked",
                    "message": (
                        "Cannot unlink the last OIDC identity — the user would "
                        "lose all means of authentication. Disable the account "
                        "instead via POST /admin/users/{user_id}/disable."
                    ),
                },
            )

        async with conn.transaction():
            await conn.execute(
                "DELETE FROM user_external_identities WHERE id = $1",
                identity_id,
            )
            await audit_log_insert(
                conn,
                "admin.user_identity_unlinked",
                actor_user_id=admin.user_id,
                actor_ip=_client_ip(request),
                target_user_id=user_id,
                metadata={
                    "identity_id": str(identity_id),
                    "provider": identity_row["provider"],
                    "external_subject": identity_row["external_subject"],
                },
            )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
