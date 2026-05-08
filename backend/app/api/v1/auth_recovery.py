"""Endpoints publics de réinitialisation de passphrase (LOT_57).

Tous les endpoints sont publics — pas d'authentification JWT/API key. La
sécurité repose sur :
- la possession des 24 mots BIP-39 (entropie 256 bits)
- l'accès à la boîte mail du user (lien envoyé par Novu)
- le compteur 3 tentatives par session
- l'expiration 30 minutes
- la détection d'anomalie (5 sessions échouées sur 24h → identity_anomaly_events)
"""
from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.db.pool import get_pool
from app.services import recovery as svc

router = APIRouter(prefix="/auth/recovery", tags=["auth-recovery"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _decode_b64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_base64",
                "message": f"{field} must be valid base64",
            },
        ) from exc


# ─── POST /start ──────────────────────────────────────────────────────────────


class StartBody(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        """Validation minimaliste : présence de `@` et longueur raisonnable.
        On évite la dépendance `email-validator` (Pydantic EmailStr) — pour
        anti-énumération, le serveur n'a pas besoin d'une validation stricte ;
        un email malformé sera traité exactement comme un email inconnu (202).
        """
        v = v.strip()
        if "@" not in v or len(v) < 3 or len(v) > 320:
            raise ValueError("invalid email format")
        return v


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
async def start(body: StartBody, request: Request) -> JSONResponse:
    """Crée une session de recovery + déclenche la notification Novu.

    Retourne **toujours** 202 — anti-énumération. L'absence de mail dans la
    boîte du user est indistinguable d'un email inconnu côté serveur.
    """
    user_agent = request.headers.get("User-Agent")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await svc.start_session(
            conn,
            email=str(body.email).lower(),
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"ok": True},
    )


# ─── GET /{id} ────────────────────────────────────────────────────────────────


@router.get("/{session_id}")
async def get_blobs(session_id: UUID) -> JSONResponse:
    """Retourne les blobs crypto nécessaires au déchiffrement client."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            blobs = await svc.get_blobs(conn, session_id)
        except svc.SessionNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            ) from exc
        except svc.SessionInvalidError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"error": exc.reason},
            ) from exc
    return JSONResponse(blobs.to_dict())


# ─── POST /{id}/attempt-failed ────────────────────────────────────────────────


@router.post("/{session_id}/attempt-failed")
async def attempt_failed(session_id: UUID) -> JSONResponse:
    """Le client signale qu'un déchiffrement a échoué (mauvais mots).

    Incrémente le compteur côté serveur. À 3 tentatives, la session passe
    automatiquement en status 'failed'.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            attempts_left = await svc.record_failed_attempt(conn, session_id)
        except svc.SessionNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            ) from exc
        except svc.SessionInvalidError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"error": exc.reason},
            ) from exc
    return JSONResponse({"attempts_left": attempts_left})


# ─── POST /{id}/complete ──────────────────────────────────────────────────────


class CompleteBody(BaseModel):
    new_salt_passphrase: str = Field(min_length=1)  # base64
    new_encrypted_rsa_private_key: str = Field(min_length=1)  # base64
    new_encrypted_sym_key_by_pass: str = Field(min_length=1)  # base64
    kdf_memory_kb: int = Field(ge=65536)
    kdf_iterations: int = Field(ge=3)
    kdf_parallelism: int = Field(ge=4)


@router.post("/{session_id}/complete")
async def complete(
    session_id: UUID,
    body: CompleteBody,
    request: Request,
) -> JSONResponse:
    """Finalise la session avec les nouveaux blobs passphrase chiffrés."""
    new_salt = _decode_b64(body.new_salt_passphrase, "new_salt_passphrase")
    if len(new_salt) != 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_salt_size",
                "message": "new_salt_passphrase must be exactly 16 bytes",
            },
        )
    new_enc_priv = _decode_b64(
        body.new_encrypted_rsa_private_key, "new_encrypted_rsa_private_key"
    )
    new_enc_sym = _decode_b64(
        body.new_encrypted_sym_key_by_pass, "new_encrypted_sym_key_by_pass"
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await svc.complete_session(
                conn,
                session_id=session_id,
                new_salt_passphrase=new_salt,
                new_encrypted_rsa_private_key=new_enc_priv,
                new_encrypted_sym_key_by_pass=new_enc_sym,
                kdf_memory_kb=body.kdf_memory_kb,
                kdf_iterations=body.kdf_iterations,
                kdf_parallelism=body.kdf_parallelism,
                ip=_client_ip(request),
            )
        except svc.SessionNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            ) from exc
        except svc.SessionInvalidError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"error": exc.reason},
            ) from exc
    return JSONResponse({"ok": True})
