"""Dependency FastAPI pour l'authentification admin JWT (rôle Keycloak) — LOT_12A."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.security import _validate_jwt


@dataclass(frozen=True)
class AdminUser:
    """Représente un admin authentifié via JWT Keycloak avec rôle harpocrate-admin."""

    keycloak_sub: str
    email: str
    display_name: str | None


async def require_admin_jwt(
    authorization: Annotated[str | None, Header()] = None,
) -> AdminUser:
    """Dependency FastAPI — valide le JWT et vérifie le rôle admin Keycloak.

    Refuse les tokens API key (hrpv_*) et les tokens sans rôle admin.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_bearer_token",
                "message": "Authorization header with Bearer token required",
            },
        )

    token = authorization[7:]

    if token.startswith("hrpv_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "admin_jwt_only",
                "message": "Admin endpoints require a JWT token, not an API key",
            },
        )

    payload = await _validate_jwt(token)

    realm_access = payload.get("realm_access", {})
    roles: list[str] = realm_access.get("roles", [])

    if settings.admin_role_name not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "admin_role_required",
                "message": f"JWT must contain role '{settings.admin_role_name}'",
            },
        )

    return AdminUser(
        keycloak_sub=payload["sub"],
        email=payload.get("email", ""),
        display_name=payload.get("name"),
    )


AdminJwt = Annotated[AdminUser, Depends(require_admin_jwt)]
