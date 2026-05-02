"""Validation JWT (Keycloak RS256 + admin local HS256) et dependency FastAPI require_jwt_user."""
from __future__ import annotations

import base64
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt.algorithms import RSAAlgorithm
from pydantic import BaseModel

from app.core.config import settings
from app.core.jwks_cache import get_jwks_key

_LOCAL_ISSUER = "harpocrate-local"


class CurrentUser(BaseModel):
    """Utilisateur courant extrait du JWT Keycloak ou admin local."""

    keycloak_sub: str
    email: str
    display_name: str | None = None


def _issuer() -> str:
    return f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"


async def _validate_local_jwt(token: str) -> dict[str, Any]:
    """Valide un JWT HS256 émis par l'endpoint local-login."""
    hmac_key = base64.b64decode(settings.hmac_key)
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            hmac_key,
            algorithms=["HS256"],
            audience=settings.keycloak_client_id,
            issuer=_LOCAL_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "token_expired", "message": "JWT token has expired"},
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
        ) from exc
    return payload


async def _validate_keycloak_jwt(token: str) -> dict[str, Any]:
    """Valide le JWT RS256 Keycloak et retourne le payload décodé."""
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
    """Dependency FastAPI — valide le JWT et retourne CurrentUser.

    Accepte deux types de tokens :
    - HS256 (alg) : token admin local émis par /v1/auth/local-login
    - RS256 (alg) : token Keycloak OIDC (chemin historique)

    Refuse explicitement les tokens commençant par 'hrpv_' (clés API).
    Refuse tout autre algorithme.
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

    # Détection de l'algorithme sans vérification de signature
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
        ) from exc

    alg: str = unverified_header.get("alg", "")

    if alg == "HS256":
        payload = await _validate_local_jwt(token)
        return CurrentUser(
            keycloak_sub=payload["sub"],
            email=payload.get("email", ""),
            display_name=payload.get("name"),
        )

    if alg == "RS256":
        payload = await _validate_keycloak_jwt(token)
        return CurrentUser(
            keycloak_sub=payload["sub"],
            email=payload.get("email", ""),
            display_name=payload.get("name"),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "unsupported_algorithm",
            "message": f"JWT algorithm '{alg}' is not supported",
        },
    )


async def _validate_jwt(token: str) -> dict[str, Any]:
    """Valide n'importe quel JWT supporté (HS256 local ou RS256 Keycloak).

    Rétro-compatibilité pour les modules qui importaient _validate_jwt directement.
    Détecte l'algorithme et délègue au validateur approprié.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
        ) from exc

    alg: str = unverified_header.get("alg", "")

    if alg == "HS256":
        return await _validate_local_jwt(token)
    if alg == "RS256":
        return await _validate_keycloak_jwt(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "unsupported_algorithm",
            "message": f"JWT algorithm '{alg}' is not supported",
        },
    )


# Type alias pour l'injection dans les routes
JwtUser = Annotated[CurrentUser, Depends(require_jwt_user)]
