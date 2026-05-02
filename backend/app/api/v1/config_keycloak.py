"""Endpoint /v1/config/keycloak — exposé sans auth pour le frontend OIDC."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/config/keycloak")
async def config_keycloak() -> dict[str, str]:
    base = f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"
    return {
        "realm": settings.keycloak_realm,
        "client_id": settings.keycloak_client_id,
        "auth_url": base,
        "token_url": f"{base}/protocol/openid-connect/token",
        "jwks_url": f"{base}/protocol/openid-connect/certs",
        "issuer": base,
    }
