"""Dependency FastAPI pour l'authentification admin JWT (rôle Keycloak) — LOT_12A."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.security import _validate_jwt
from app.services import admin_user_resolver


@dataclass(frozen=True)
class AdminUser:
    """Représente un admin authentifié via JWT (Keycloak ou local).

    `user_id` pointe sur une row `users` (potentiellement is_system=TRUE pour
    le local-admin ou un admin Keycloak pré-bootstrap). Permet d'utiliser
    cet UUID comme `actor_user_id` dans `audit_log` sans violer la
    contrainte `audit_log_one_actor`.
    """

    user_id: UUID
    keycloak_sub: str
    email: str
    display_name: str | None


async def require_admin_jwt(
    authorization: Annotated[str | None, Header()] = None,
) -> AdminUser:
    """Dependency FastAPI — valide le JWT et vérifie le rôle admin Keycloak.

    Refuse les tokens API key (hrpv_*) et les tokens sans rôle admin.
    Résout également `users.id` pour la traçabilité audit_log.
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

    keycloak_sub = payload["sub"]
    email = payload.get("email", "")
    display_name = payload.get("name")

    user_id = await admin_user_resolver.resolve_admin_user_id(
        keycloak_sub=keycloak_sub,
        email=email,
        display_name=display_name,
    )

    return AdminUser(
        user_id=user_id,
        keycloak_sub=keycloak_sub,
        email=email,
        display_name=display_name,
    )


AdminJwt = Annotated[AdminUser, Depends(require_admin_jwt)]