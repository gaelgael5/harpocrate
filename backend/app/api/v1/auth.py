"""Endpoints /v1/me/* — gestion du compte utilisateur bootstrappé."""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.models.api.auth import (
    BootstrapRequest,
    BootstrapResponse,
    CryptoResponse,
    KdfParams,
    MeResponse,
    PassphraseChangeRequest,
    RecoveryCryptoResponse,
    RecoveryRenewRequest,
    UpdatedAtResponse,
)
from app.models.db.user import UserRow
from app.services import auth as auth_svc
from app.services.audit import audit_log_insert

router = APIRouter(prefix="/me", tags=["auth"])


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _me_response(user: UserRow) -> MeResponse:
    return MeResponse(
        id=user.id,
        keycloak_sub=user.keycloak_sub,
        email=user.email,
        display_name=user.display_name,
        has_bootstrap=True,
        kdf_params=KdfParams(
            memory_kb=user.kdf_memory_kb,
            iterations=user.kdf_iterations,
            parallelism=user.kdf_parallelism,
        ),
        rsa_key_size=user.rsa_key_size,
        created_at=user.created_at,
        last_unlock_at=user.last_unlock_at,
        preferred_locale=getattr(user, 'preferred_locale', 'en'),
    )


@router.get("")
async def get_me(current_user: JwtUser) -> JSONResponse:
    """Retourne les infos de l'utilisateur courant.

    404 avec error=first_login si l'utilisateur n'a pas encore bootstrappé.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)

    if user is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "first_login",
                "message": "User must complete bootstrap before using the vault",
                "details": {
                    "keycloak_sub": current_user.keycloak_sub,
                    "email": current_user.email,
                },
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_me_response(user).model_dump(mode="json"),
    )


@router.post("/bootstrap", status_code=status.HTTP_201_CREATED)
async def bootstrap(
    req: BootstrapRequest,
    current_user: JwtUser,
) -> JSONResponse:
    """Bootstrap le matériel cryptographique de l'utilisateur.

    201 si succès, 409 si déjà bootstrappé, 400 si paramètres invalides.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_id = await auth_svc.bootstrap_user(
            conn,
            keycloak_sub=current_user.keycloak_sub,
            email=current_user.email,
            display_name=current_user.display_name,
            req=req,
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=BootstrapResponse(user_id=user_id).model_dump(mode="json"),
    )


@router.get("/crypto")
async def get_crypto(current_user: JwtUser, request: Request) -> JSONResponse:
    """Retourne les blobs crypto passphrase.

    Side-effect : met à jour last_unlock_at + audit user.crypto_accessed.
    """
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        user = await users_repo.get_crypto(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": "first_login",
                    "message": "User must complete bootstrap before using the vault",
                },
            )

        await users_repo.touch_last_unlock(conn, user_id=user.id)
        await audit_log_insert(
            conn,
            "user.crypto_accessed",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"keycloak_sub": user.keycloak_sub},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=CryptoResponse(
            salt_passphrase=_b64(user.salt_passphrase),
            encrypted_rsa_private_key=_b64(user.encrypted_rsa_private_key),
            encrypted_sym_key_by_pass=_b64(user.encrypted_sym_key_by_pass),
            kdf_params=KdfParams(
                memory_kb=user.kdf_memory_kb,
                iterations=user.kdf_iterations,
                parallelism=user.kdf_parallelism,
            ),
            rsa_public_key=_b64(user.rsa_public_key),
        ).model_dump(mode="json"),
    )


@router.get("/crypto/recovery")
async def get_crypto_recovery(current_user: JwtUser) -> JSONResponse:
    """Retourne les blobs crypto recovery.

    Audit : user.recovery_accessed.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": "first_login",
                    "message": "User must complete bootstrap before using the vault",
                },
            )

        await audit_log_insert(
            conn,
            "user.recovery_accessed",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"keycloak_sub": user.keycloak_sub, "sensitive": True},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=RecoveryCryptoResponse(
            salt_recovery=_b64(user.salt_recovery),
            encrypted_sym_key_by_recovery=_b64(user.encrypted_sym_key_by_recovery),
        ).model_dump(mode="json"),
    )


@router.put("/passphrase")
async def change_passphrase(
    req: PassphraseChangeRequest,
    current_user: JwtUser,
) -> JSONResponse:
    """Met à jour les blobs passphrase."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": "first_login",
                    "message": "User must complete bootstrap before using the vault",
                },
            )

        updated_at = await auth_svc.change_passphrase(conn, user=user, req=req)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=UpdatedAtResponse(updated_at=updated_at).model_dump(mode="json"),
    )


@router.put("/recovery")
async def renew_recovery(
    req: RecoveryRenewRequest,
    current_user: JwtUser,
) -> JSONResponse:
    """Met à jour le blob recovery."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": "first_login",
                    "message": "User must complete bootstrap before using the vault",
                },
            )

        updated_at = await auth_svc.renew_recovery(conn, user=user, req=req)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=UpdatedAtResponse(updated_at=updated_at).model_dump(mode="json"),
    )


class PreferencesUpdate(BaseModel):
    preferred_locale: str

    @field_validator("preferred_locale")
    @classmethod
    def validate_locale(cls, v: str) -> str:
        if v not in ("en", "fr"):
            raise ValueError("preferred_locale must be 'en' or 'fr'")
        return v


@router.patch("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    current_user: JwtUser,
) -> JSONResponse:
    """Met à jour les préférences de l'utilisateur (locale)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "user_not_found"},
            )
        await conn.execute(
            "UPDATE users SET preferred_locale = $1 WHERE id = $2",
            body.preferred_locale,
            user.id,
        )

    return JSONResponse({"preferred_locale": body.preferred_locale})
