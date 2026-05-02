"""Endpoints /v1/me/identities/*, /v1/me/anomalies/*, /v1/me/reverify/*, /v1/me/quarantine/*.

LOT_02 governance — gestion multi-provider, anomalies, reverify token, quarantine.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import anomalies as anomalies_repo
from app.db.repositories import identities as identities_repo
from app.db.repositories import reverify_tokens as reverify_repo
from app.db.repositories import users as users_repo
from app.models.api.identity import (
    AnomaliesListResponse,
    AnomalyResponse,
    ExternalIdentityResponse,
    IdentitiesListResponse,
    QuarantineStatusResponse,
    ReverifyChallengeResponse,
)
from app.services.audit import audit_log_insert

router = APIRouter(prefix="/me", tags=["identity-governance"])


def _truncate_sub(sub: str) -> str:
    """Tronque external_subject pour ne jamais l'exposer en clair."""
    return sub[:7] + "..." if len(sub) > 7 else sub + "..."


# ─── Identités ───────────────────────────────────────────────────────────────


@router.get("/identities")
async def list_identities(current_user: JwtUser) -> JSONResponse:
    """Liste les identités externes de l'utilisateur courant."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        rows = await identities_repo.list_by_user(conn, user.id)

    identities = [
        ExternalIdentityResponse(
            id=row.id,
            provider=row.provider,
            external_subject=_truncate_sub(row.external_subject),
            is_primary=row.is_primary,
            linked_at=row.linked_at,
            last_login_at=row.last_login_at,
            linked_email=row.linked_email,
            linked_display_name=row.linked_display_name,
        )
        for row in rows
    ]
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=IdentitiesListResponse(identities=identities).model_dump(mode="json"),
    )


@router.delete("/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_identity(
    identity_id: UUID,
    current_user: JwtUser,
    x_reverify_token: Annotated[str | None, Header()] = None,
) -> None:
    """Délie une identité externe. Refuse si c'est la dernière ou la primary."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "first_login", "message": "User must bootstrap first"},
            )
        user_id = user.id

        identities = await identities_repo.list_by_user(conn, user_id)

        if len(identities) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "cannot_unlink_last",
                    "message": "Cannot unlink the last identity",
                },
            )

        target = next((i for i in identities if i.id == identity_id), None)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "identity_not_found"},
            )

        if target.is_primary:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "cannot_remove_primary_identity",
                    "message": "Promote another identity to primary first",
                },
            )

        deleted = await identities_repo.delete(conn, identity_id, user_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "identity_not_found"},
            )

        await audit_log_insert(
            conn,
            "user.identity_unlinked",
            actor_user_id=user_id,
            target_user_id=user_id,
            metadata={"identity_id": str(identity_id), "provider": target.provider},
        )


@router.post("/identities/{identity_id}/set-primary")
async def set_primary_identity(
    identity_id: UUID,
    current_user: JwtUser,
) -> JSONResponse:
    """Désigne une identité comme primary et met à jour users.email."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        user_id = user.id

        identities = await identities_repo.list_by_user(conn, user_id)
        target = next((i for i in identities if i.id == identity_id), None)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "identity_not_found"},
            )

        async with conn.transaction():
            await identities_repo.set_primary(conn, identity_id, user_id)
            if target.linked_email:
                await users_repo.set_email(conn, user_id=user_id, email=target.linked_email)

        await audit_log_insert(
            conn,
            "user.identity_primary_changed",
            actor_user_id=user_id,
            target_user_id=user_id,
            metadata={
                "identity_id": str(identity_id),
                "provider": target.provider,
                "new_email": target.linked_email,
            },
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ─── Anomalies ───────────────────────────────────────────────────────────────


@router.get("/anomalies")
async def list_anomalies(
    current_user: JwtUser,
    only_unacknowledged: bool = False,
) -> JSONResponse:
    """Liste les anomalies de l'utilisateur courant."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        rows = await anomalies_repo.list_by_user(
            conn,
            user.id,
            only_unacknowledged=only_unacknowledged,
        )

    anomalies = [
        AnomalyResponse(
            id=row.id,
            detected_at=row.detected_at,
            severity=row.severity,  # type: ignore[arg-type]
            anomaly_type=row.anomaly_type,
            metadata=(
                row.metadata
                if isinstance(row.metadata, dict)
                else None
            ),
            acknowledged_at=row.acknowledged_at,
            acknowledged_by_user_id=row.acknowledged_by_user_id,
        )
        for row in rows
    ]
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=AnomaliesListResponse(anomalies=anomalies).model_dump(mode="json"),
    )


@router.post("/anomalies/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(
    anomaly_id: int,
    current_user: JwtUser,
) -> JSONResponse:
    """Acquitte une anomalie."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        user_id = user.id

        updated = await anomalies_repo.acknowledge(
            conn,
            anomaly_id=anomaly_id,
            user_id=user_id,
            by_user_id=user_id,
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "anomaly_not_found_or_already_acknowledged"},
            )

        await audit_log_insert(
            conn,
            "user.anomaly_acknowledged",
            actor_user_id=user_id,
            target_user_id=user_id,
            metadata={"anomaly_id": anomaly_id},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ─── Reverify token ───────────────────────────────────────────────────────────


@router.post("/reverify/challenge")
async def reverify_challenge(current_user: JwtUser) -> JSONResponse:
    """Émet un token reverify one-shot valide 5 minutes.

    Le client doit présenter ce token dans X-Reverify-Token pour les actions
    sensibles (changement passphrase, recovery rotate, sortie quarantaine).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        user_id = user.id

        raw_token, token_hash = reverify_repo.generate_token()
        token_row_id = await reverify_repo.insert(conn, user_id, token_hash)
        row = await conn.fetchrow(
            "SELECT expires_at FROM reverify_tokens WHERE id = $1",
            token_row_id,
        )
        expires_at = row["expires_at"] if row else None

        await audit_log_insert(
            conn,
            "user.reverify_challenge_issued",
            actor_user_id=user_id,
            target_user_id=user_id,
        )

    resp = ReverifyChallengeResponse(
        reverify_token=raw_token,
        expires_at=expires_at,
        ttl_seconds=reverify_repo.REVERIFY_TTL_SECONDS,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=resp.model_dump(mode="json"),
    )


# ─── Quarantaine ─────────────────────────────────────────────────────────────


@router.get("/quarantine")
async def get_quarantine_status(current_user: JwtUser) -> JSONResponse:
    """Retourne le statut de quarantaine de l'utilisateur."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found"},
        )

    from app.services.identity_governance import is_in_quarantine

    resp = QuarantineStatusResponse(
        in_quarantine=is_in_quarantine(user),
        quarantine_until=user.quarantine_until,
        quarantine_reason=user.quarantine_reason,
        force_reverify_next_login=user.force_reverify_next_login,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=resp.model_dump(mode="json"),
    )


@router.post("/quarantine/exit")
async def quarantine_exit(
    current_user: JwtUser,
    x_reverify_token: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Lève la quarantaine. Nécessite un X-Reverify-Token valide."""
    if not x_reverify_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "reverify_required", "message": "X-Reverify-Token header required"},
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )
        user_id = user.id

        token_row = await reverify_repo.consume(conn, user_id, x_reverify_token)
        if token_row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "reverify_token_invalid_or_expired"},
            )

        await users_repo.clear_quarantine(conn, user_id=user_id)

        await audit_log_insert(
            conn,
            "user.quarantine_exit",
            actor_user_id=user_id,
            target_user_id=user_id,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
