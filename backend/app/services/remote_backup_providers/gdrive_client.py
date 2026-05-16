"""Couche d'abstraction sur les libs Google.

Toutes les fonctions ici sont sync. Les callers (provider, service OAuth) les
appellent via asyncio.to_thread. Les tests mockent ce module — JAMAIS
googleapiclient directement.
"""

from __future__ import annotations

from typing import Any

import google.auth.transport.requests as _g_requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import Resource, build

_DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_credentials(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_uri: str = _TOKEN_URI,
    scope: str = _DRIVE_FILE_SCOPE,
) -> Credentials:
    """Construit un objet Credentials prêt à refresh."""
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=token_uri,
        scopes=[scope],
    )


def refresh(creds: Credentials) -> None:
    """Force le refresh de l'access_token (lève RefreshError si invalid_grant)."""
    creds.refresh(_g_requests.Request())


def build_drive_service(creds: Credentials) -> Resource:
    """Construit le client Drive v3 (cache local du discovery doc géré par la lib)."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def build_flow(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> Flow:
    """Construit un Flow OAuth pour échanger un code contre des tokens."""
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": _TOKEN_URI,
            }
        },
        scopes=[_DRIVE_FILE_SCOPE],
        redirect_uri=redirect_uri,
    )


def fetch_user_email(creds: Credentials) -> str:
    """Récupère l'email du user autorisateur via l'endpoint userinfo OpenID."""
    service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info: dict[str, Any] = service.userinfo().get().execute()
    email = info.get("email") or ""
    return str(email)


__all__ = [
    "build_credentials",
    "build_drive_service",
    "build_flow",
    "fetch_user_email",
    "refresh",
]
