"""Endpoints /v1/users/* — lookup utilisateur par email (LOT_03)."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.db.repositories import wallets as wallets_repo
from app.models.api.wallets import UserLookupResponse
from app.services.audit import audit_log_insert
from app.services.wallets import rate_limit_lookup

router = APIRouter(prefix="/users", tags=["users"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("/lookup")
async def lookup_user(
    current_user: JwtUser,
    request: Request,
    email: str = Query(...),
) -> JSONResponse:
    """Lookup d'un utilisateur par email, pour préparer un partage.

    Rate-limité à 30 req/min/IP.
    """
    ip = _client_ip(request) or "unknown"
    await rate_limit_lookup(ip)

    pool = await get_pool()
    async with pool.acquire() as conn:
        caller = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if caller is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        found = await wallets_repo.get_user_by_email(conn, email)

        await audit_log_insert(
            conn,
            "user.lookup",
            actor_user_id=caller.id,
            actor_ip=ip,
            metadata={
                "lookup_email": email,
                "found": found is not None,
            },
            success=found is not None,
        )

        if found is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "user_not_found", "message": "No user found with this email"},
            )

    rsa_pub_b64 = base64.b64encode(found["rsa_public_key"]).decode()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=UserLookupResponse(
            user_id=found["id"],
            email=found["email"],
            display_name=found["display_name"],
            rsa_public_key=rsa_pub_b64,
        ).model_dump(mode="json"),
    )
