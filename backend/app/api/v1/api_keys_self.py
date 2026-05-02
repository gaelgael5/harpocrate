"""Endpoints /v1/api-keys/{api_key_id}/* — auto-service SDK (LOT_09).

Ces endpoints sont appelés par le SDK Python (harpocrate-gen) avec un token
hrpv_* pour obtenir des métadonnées sans connaître le wallet_id à l'avance.

Sécurité : l'endpoint valide le token complet (HMAC + Argon2id) avant de
retourner quoi que ce soit. L'appelant ne peut obtenir que les infos de sa
propre clé (api_key_id extrait du token lui-même).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.api_key_auth import ApiKeyCaller, require_api_key

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys-self"],
)


# ─── GET /v1/api-keys/{api_key_id}/wallet-id ─────────────────────────────────


@router.get("/{api_key_id}/wallet-id")
async def get_api_key_wallet_id(
    api_key_id: UUID,
    caller: ApiKeyCaller = Depends(require_api_key),
) -> JSONResponse:
    """Retourne le wallet_id associé à l'API key courante.

    Utilisé par le SDK Python pour initialiser VaultClient sans que l'appelant
    ait à connaître le wallet_id à l'avance.

    L'api_key_id dans le path doit correspondre à celui du token Bearer.
    Lève 403 si le path api_key_id ne correspond pas au token présenté.
    """
    if caller.api_key_id != api_key_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "api_key_id in path does not match the presented token",
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "api_key_id": str(caller.api_key_id),
            "wallet_id": str(caller.wallet_id),
        },
    )
