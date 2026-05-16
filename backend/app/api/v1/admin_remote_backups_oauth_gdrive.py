"""Endpoints OAuth Google Drive pour les connexions de backup distantes.

Tous protégés par AdminJwt (sauf /callback qui est appelé par Google et utilise
le state OAuth pour la CSRF protection). Préfixe /admin/backup-remotes/oauth/gdrive.
"""

from __future__ import annotations

import json as _json

from fastapi import APIRouter, Path, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.db.repositories import oauth_pending_session as repo
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


# ─── GET /callback ───────────────────────────────────────────────────────────

_CALLBACK_HTML_OK = """<!doctype html>
<html><head><meta charset="utf-8"><title>Google Drive Authorization</title></head>
<body>
<p>Authorization complete. This window will close automatically.</p>
<script>
(function () {{
  var msg = {{ type: 'gdrive_oauth_done', state: {state_js}, ok: {ok_js}, error: {error_js} }};
  if (window.opener) {{ window.opener.postMessage(msg, window.location.origin); }}
  window.close();
}})();
</script>
</body></html>"""

_CALLBACK_HTML_ERROR_NO_STATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Authorization error</title></head>
<body>
<p>Authorization error: invalid or expired state. You can close this window.</p>
</body></html>"""


def _render_callback_html(state: str, ok: bool, error: str | None) -> str:
    return _CALLBACK_HTML_OK.format(
        state_js=_json.dumps(state),
        ok_js=_json.dumps(ok),
        error_js=_json.dumps(error),
    )


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Callback Google OAuth — pas d'AdminJwt (Google appelle directement).

    La protection CSRF passe par le state vérifié contre oauth_pending_session.
    Retourne du HTML auto-fermant qui notifie l'opener via postMessage.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await repo.get_active_by_state(conn, state)
        if existing is None:
            return HTMLResponse(_CALLBACK_HTML_ERROR_NO_STATE, status_code=400)

        if error:
            await svc.mark_session_failed(conn, state=state, error=error)
            return HTMLResponse(_render_callback_html(state, False, error))

        if not code:
            await svc.mark_session_failed(conn, state=state, error="missing_code")
            return HTMLResponse(_render_callback_html(state, False, "missing_code"))

        try:
            await svc.finalize_session(conn, state=state, code=code)
        except svc.OAuthSessionError as exc:
            await svc.mark_session_failed(conn, state=state, error=str(exc))
            return HTMLResponse(_render_callback_html(state, False, str(exc)))

    return HTMLResponse(_render_callback_html(state, True, None))


# ─── GET /session/{state} ────────────────────────────────────────────────────


@router.get("/session/{state}", response_class=JSONResponse)
async def get_oauth_session(
    admin: AdminJwt,
    state: str = Path(..., min_length=1, max_length=128),
) -> JSONResponse:
    """Vue publique de la session OAuth — sans aucun secret.

    Le frontend appelle ce endpoint après réception du postMessage de la popup
    pour récupérer user_email (ou error). NE retourne JAMAIS refresh_token,
    client_secret, ou autre clé sensible.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_by_state(conn, state)
    return JSONResponse(svc.public_session_view(row))
