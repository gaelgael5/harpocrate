"""Endpoints REST appairage maître/standby (LOT 2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.db.repositories import pairing_sessions as repo
from app.models.api.pairing import (
    PairingAcceptRequest,
    PairingAcceptResponse,
    PairingAcceptV2Request,
    PairingConfirmRequest,
    PairingConfirmResponse,
    PairingConfirmV2Request,
    PairingInitRequest,
    PairingInitResponse,
    PairingInitV2Request,
    PairingInitV2Response,
    PairingStatusResponse,
)
from app.services import pairing as svc
from app.services import pairing_steps as steps_svc
from app.services import pairing_v2 as svc_v2
from app.services.pairing_url_codec import InvalidPairingUrlError

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


# ─── V2 — échange d'URL d'appairage (LOT 5) ──────────────────────────────────


@router.post(
    "/init-v2",
    response_model=PairingInitV2Response,
    status_code=status.HTTP_200_OK,
)
async def init_pairing_v2(
    req: PairingInitV2Request,
    admin: AdminJwt,
) -> PairingInitV2Response:
    """A crée une session et retourne une URL d'appairage à transmettre à B."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await svc_v2.init_master_v2(
                conn,
                standby_url=req.standby_url,
                actor_user_id=admin.user_id,
            )
        except svc.PairingAcceptError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_standby_url", "cause": str(e)},
            ) from e
    return PairingInitV2Response(
        session_id=result.session_id,
        pairing_url=result.pairing_url,
        expires_in_seconds=result.expires_in_seconds,
    )


@router.post(
    "/confirm-v2",
    response_model=PairingConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_pairing_v2(req: PairingConfirmV2Request) -> PairingConfirmResponse:
    """B → A : confirmation inter-instances avec (session_id, token).

    Authentification = token aléatoire 128 bits + TTL court (pas de JWT, pour
    les mêmes raisons que l'endpoint /confirm v1).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            payload = await svc_v2.confirm_master_v2(
                conn,
                session_id=req.session_id,
                token=req.token,
                standby_url=req.standby_url,
                actor_user_id=None,
                force=req.force,
            )
        except svc.NodeAlreadyExistsError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "node_already_exists",
                    "existing_node": e.existing_node,
                },
            ) from e
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "invalid_or_expired_token"},
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
    "/accept-v2",
    response_model=PairingAcceptResponse,
    status_code=status.HTTP_200_OK,
)
async def accept_pairing_v2(
    req: PairingAcceptV2Request,
    admin: AdminJwt,
) -> PairingAcceptResponse:
    """B colle l'URL d'appairage reçue de A → contact A et démarre le wizard."""
    from app.core.config import settings

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            sid = await svc_v2.accept_standby_v2(
                conn,
                pairing_url=req.pairing_url,
                self_url=settings.public_url,
                actor_user_id=admin.user_id,
            )
        except InvalidPairingUrlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_pairing_url", "cause": str(e)},
            ) from e
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "invalid_or_expired_token"},
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


@router.get("/{session_id}/steps")
async def get_steps(
    session_id: UUID,
    admin: AdminJwt,
) -> JSONResponse:
    """Liste les commandes wizard à exécuter par l'admin pour ce standby."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await repo.get(conn, session_id)
    if sess is None or sess["role"] != "standby":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "session_not_found"},
        )
    p = sess["payload"]
    if not isinstance(p, dict) or "master_host" not in p:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "payload_incomplete"},
        )
    steps = steps_svc.build_standby_steps(
        master_host=p["master_host"],
        master_port=p["master_port"],
        replication_user=p["replication_user"],
        replication_password=p["replication_password"],
        application_name=p["application_name"],
    )
    return JSONResponse(
        {
            "steps": [
                {"idx": s.idx, "title": s.title, "command": s.command, "hint": s.hint}
                for s in steps
            ],
            "current_step_idx": sess["current_step_idx"],
            "status": sess["status"],
        }
    )


@router.post("/{session_id}/steps/{idx}/done")
async def step_done(
    session_id: UUID,
    idx: int,
    admin: AdminJwt,
) -> JSONResponse:
    """Marque l'étape `idx` comme exécutée et avance le curseur."""
    # Le total est figé pour build_standby_steps — gardons-le en sync.
    total = 8
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_idx = await svc.advance_step(
                conn,
                session_id=session_id,
                current_idx=idx,
                total=total,
                actor_user_id=admin.user_id,
            )
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            ) from None
        except svc.StepCursorMismatchError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "step_cursor_mismatch", "cause": str(e)},
            ) from None
    return JSONResponse({"current_step_idx": new_idx})


@router.post("/{session_id}/steps/{idx}/back")
async def step_back(
    session_id: UUID,
    idx: int,
    admin: AdminJwt,
) -> JSONResponse:
    """Recule d'une étape (curseur idempotent à 0)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_idx = await svc.back_step(
                conn,
                session_id=session_id,
                current_idx=idx,
            )
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            ) from None
        except svc.StepCursorMismatchError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "step_cursor_mismatch", "cause": str(e)},
            ) from None
    return JSONResponse({"current_step_idx": new_idx})
