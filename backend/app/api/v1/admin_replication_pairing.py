"""Endpoints REST appairage maître/standby (LOT 2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.db.repositories import pairing_sessions as repo
from app.models.api.pairing import (
    PairingAcceptRequest,
    PairingAcceptResponse,
    PairingConfirmRequest,
    PairingConfirmResponse,
    PairingInitRequest,
    PairingInitResponse,
    PairingStatusResponse,
)
from app.services import pairing as svc

router = APIRouter(
    prefix="/admin/replication/pairing",
    tags=["admin-replication-pairing"],
)


@router.post(
    "/init",
    response_model=PairingInitResponse,
    status_code=status.HTTP_200_OK,
)
async def init_pairing(
    req: PairingInitRequest,
    admin: AdminJwt,
) -> PairingInitResponse:
    """A initie un appairage : retourne un code 4 chiffres à transmettre à B."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await svc.init_master(
            conn,
            partner_url=req.partner_url,
            actor_user_id=admin.user_id,
        )
    return PairingInitResponse(
        session_id=result.session_id,
        code=result.code,
        expires_in_seconds=result.expires_in_seconds,
    )


@router.post(
    "/confirm",
    response_model=PairingConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_pairing(req: PairingConfirmRequest) -> PairingConfirmResponse:
    """Appelé inter-instances : B → A avec le code 4 chiffres.

    Authentification = code + TTL court (pas de JWT, sinon B devrait stocker un
    JWT admin de A, ce qu'on veut éviter).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            payload = await svc.confirm_master(
                conn,
                code=req.code,
                standby_url=req.standby_url,
                actor_user_id=None,
            )
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "invalid_or_expired_code"},
            ) from None
        except svc.TooManyAttemptsError:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "too_many_attempts"},
            ) from None
        except svc.InvalidPairingPreconditionError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "invalid_pairing_precondition", "cause": str(e)},
            ) from e
        except svc.PairingAcceptError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "pairing_accept_error", "cause": str(e)},
            ) from e
    return PairingConfirmResponse(**payload)


@router.post(
    "/accept",
    response_model=PairingAcceptResponse,
    status_code=status.HTTP_200_OK,
)
async def accept_pairing(
    req: PairingAcceptRequest,
    admin: AdminJwt,
) -> PairingAcceptResponse:
    """B initie l'appairage : contacte A avec le code reçu hors-bande."""
    # Import tardif : évite l'instanciation de Settings à la collecte pytest.
    from app.core.config import settings

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            sid = await svc.accept_standby(
                conn,
                master_url=req.master_url,
                code=req.code,
                self_url=settings.public_url,
                actor_user_id=admin.user_id,
            )
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "invalid_or_expired_code"},
            ) from None
        except svc.TooManyAttemptsError:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "too_many_attempts"},
            ) from None
        except svc.PairingAcceptError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "pairing_accept_error", "cause": str(e)},
            ) from e
    return PairingAcceptResponse(session_id=sid)


@router.get("/{session_id}/status", response_model=PairingStatusResponse)
async def get_status(
    session_id: UUID,
    admin: AdminJwt,
) -> PairingStatusResponse:
    """État courant d'une session d'appairage."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await repo.get(conn, session_id)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "session_not_found"},
        )
    return PairingStatusResponse(
        session_id=sess["id"],
        role=sess["role"],
        status=sess["status"],
        partner_url=sess["partner_url"],
        current_step_idx=sess["current_step_idx"],
        expires_at=sess["expires_at"].isoformat(),
    )
