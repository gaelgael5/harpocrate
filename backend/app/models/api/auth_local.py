"""Schemas Pydantic pour les endpoints /v1/auth/local-* (auth locale)."""
from __future__ import annotations

from pydantic import BaseModel


class LocalLoginRequest(BaseModel):
    """Corps de POST /v1/auth/local-login."""

    username: str
    password: str


class LocalLoginResponse(BaseModel):
    """Réponse de POST /v1/auth/local-login."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class AuthModesResponse(BaseModel):
    """Réponse de GET /v1/config/auth-modes."""

    oidc: bool = True
    local_login: bool
