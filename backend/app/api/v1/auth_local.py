"""Endpoints d'authentification locale (alternative à Keycloak OIDC).

POST /v1/auth/local-login  — login username/password depuis .env
GET  /v1/config/auth-modes — modes d'authentification disponibles (public)
"""
from __future__ import annotations

import base64
import hmac
import time

import jwt
import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.models.api.auth_local import AuthModesResponse, LocalLoginRequest, LocalLoginResponse

log = structlog.get_logger(__name__)

router = APIRouter(tags=["auth-local"])

_LOCAL_ISSUER = "harpocrate-local"
_TOKEN_TTL_SECONDS = 86400  # 24 h


def _build_local_jwt() -> str:
    """Génère un JWT HS256 pour l'admin local."""
    hmac_key = base64.b64decode(settings.hmac_key)
    now = int(time.time())
    payload = {
        "sub": "local-admin",
        "email": settings.admin_local_email,
        "name": settings.admin_local_display_name,
        "iss": _LOCAL_ISSUER,
        "aud": settings.keycloak_client_id,
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, hmac_key, algorithm="HS256")


def _credentials_match(attempted_username: str, attempted_password: str) -> bool:
    """Comparaison en temps constant — vérifie toujours les deux champs."""
    username_ok = hmac.compare_digest(
        attempted_username.encode(),
        settings.admin_local_username.encode(),
    )
    password_ok = hmac.compare_digest(
        attempted_password.encode(),
        settings.admin_local_password.encode(),
    )
    # On n'utilise pas de short-circuit : les deux comparaisons sont toujours exécutées.
    return username_ok and password_ok


@router.get("/config/auth-modes", response_model=AuthModesResponse)
async def get_auth_modes() -> JSONResponse:
    """Retourne les modes d'authentification disponibles (pas d'auth requise)."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=AuthModesResponse(
            oidc=True,
            local_login=settings.admin_local_enabled,
            dev_mode=settings.dev_mode,
            dev_mode_label=settings.dev_mode_label,
        ).model_dump(),
    )


@router.post("/auth/local-login")
async def local_login(req: LocalLoginRequest, request: Request) -> JSONResponse:
    """Authentification admin locale par username/password.

    Si admin_local_enabled=False, retourne 404 (n'expose pas l'existence de la route).
    Toujours en temps constant — les deux champs sont toujours comparés.
    """
    if not settings.admin_local_enabled:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": "Not found"},
        )

    matched = _credentials_match(req.username, req.password)

    # Audit via structlog (le local-admin n'est pas en DB → impossible d'utiliser
    # audit_log qui exige un actor_user_id ou actor_api_key_id).
    # Le log JSON part dans Loki via Alloy → traçable côté Grafana.
    actor_ip = request.client.host if request.client else None
    log.info(
        "auth.local_login",
        username=req.username,
        actor_ip=actor_ip,
        success=matched,
        error_code=None if matched else "invalid_credentials",
    )

    if not matched:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "invalid_credentials",
                "message": "Invalid username or password",
            },
        )

    token = _build_local_jwt()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=LocalLoginResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=_TOKEN_TTL_SECONDS,
        ).model_dump(),
    )
