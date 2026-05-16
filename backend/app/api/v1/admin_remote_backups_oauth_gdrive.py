"""Endpoints OAuth Google Drive pour les connexions de backup distantes.

Tous protégés par AdminJwt (sauf /callback qui est appelé par Google et utilise
le state OAuth pour la CSRF protection). Préfixe /admin/backup-remotes/oauth/gdrive.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.services import gdrive_oauth_session as svc

router = APIRouter(
    prefix="/admin/backup-remotes/oauth/gdrive",
    tags=["admin-remote-backups-oauth-gdrive"],
)

_CALLBACK_SUFFIX = "/v1/admin/backup-remotes/oauth/gdrive/callback"


def _canonical_redirect_uri() -> str:
    base = settings.public_url.rstrip("/")
    return f"{base}{_CALLBACK_SUFFIX}"


# ─── GET /redirect-uri ───────────────────────────────────────────────────────


@router.get("/redirect-uri", response_class=JSONResponse)
async def get_redirect_uri(admin: AdminJwt) -> JSONResponse:
    """Retourne le redirect_uri canonique à coller dans Google Cloud Console."""
    return JSONResponse({"redirect_uri": _canonical_redirect_uri()})


# ─── POST /start ─────────────────────────────────────────────────────────────


class StartRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    folder_name: str = Field(min_length=1, max_length=255)


@router.post("/start", response_class=JSONResponse)
async def start_oauth_flow(body: StartRequest, admin: AdminJwt) -> JSONResponse:
    """Démarre un flow OAuth gdrive. Retourne {auth_url, state}."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        out = await svc.create_pending_session(
            conn,
            name=body.name,
            client_id=body.client_id,
            client_secret=body.client_secret,
            folder_name=body.folder_name,
            redirect_uri=_canonical_redirect_uri(),
            target_connection_id=None,
            created_by_user_id=None,
        )
    return JSONResponse(out)
