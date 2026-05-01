"""Validation JWT Keycloak et dependency FastAPI require_jwt_user."""
from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt.algorithms import RSAAlgorithm
from pydantic import BaseModel

from app.core.config import settings
from app.core.jwks_cache import get_jwks_key


class CurrentUser(BaseModel):
    """Utilisateur courant extrait du JWT Keycloak."""

    keycloak_sub: str
    email: str
    display_name: str | None = None


def _issuer() -> str:
    return f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"


async def _validate_jwt(token: str) -> dict[str, Any]:
    """Valide le JWT et retourne le payload décodé."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
        ) from exc

    kid: str | None = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_kid", "message": "JWT header missing 'kid'"},
        )

    try:
        jwk_dict = await get_jwks_key(kid)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unknown_kid", "message": str(exc)},
        ) from exc

    try:
        public_key = RSAAlgorithm.from_jwk(jwk_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_jwk", "message": str(exc)},
        ) from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            public_key,  # type: ignore[arg-type]
            algorithms=["RS256"],
            audience=settings.keycloak_client_id,
            issuer=_issuer(),
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "token_expired", "message": "JWT token has expired"},
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_audience", "message": str(exc)},
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
        ) from exc

    return payload


async def require_jwt_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Dependency FastAPI — valide le JWT Keycloak et retourne CurrentUser.

    Refuse explicitement les tokens commençant par 'hrpv_' (clés API).
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
                "error": "api_key_not_allowed_here",
                "message": "API keys are not accepted on /me/* endpoints",
            },
        )

    payload = await _validate_jwt(token)

    return CurrentUser(
        keycloak_sub=payload["sub"],
        email=payload.get("email", ""),
        display_name=payload.get("name"),
    )


# Type alias pour l'injection dans les routes
JwtUser = Annotated[CurrentUser, Depends(require_jwt_user)]
