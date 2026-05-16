"""Service — orchestration des sessions OAuth Google Drive.

Gère le cycle de vie d'une oauth_pending_session :
  create_pending_session -> [callback Google] -> finalize_session -> [save] -> DELETE.

Pas d'I/O HTTP entrant — c'est le rôle du router. Les appels Google passent
par gdrive_client (mockable).
"""

from __future__ import annotations

import logging
import secrets
from typing import Any
from uuid import UUID

import asyncpg

from app.db.repositories import oauth_pending_session as repo
from app.services.audit import audit_log_insert
from app.services.remote_backup_providers import gdrive_client

_log = logging.getLogger(__name__)
_PROVIDER = "gdrive"
_TTL_SECONDS = 10 * 60  # 10 min


class OAuthSessionError(Exception):
    """Erreur métier OAuth (state inconnu, expiré, déjà consommé, etc.)."""


async def create_pending_session(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    name: str,
    client_id: str,
    client_secret: str,
    folder_name: str,
    redirect_uri: str,
    target_connection_id: UUID | None,
    created_by_user_id: UUID | None,
) -> dict[str, str]:
    """Crée une oauth_pending_session, retourne {auth_url, state}."""
    state = secrets.token_urlsafe(32)
    flow = gdrive_client.build_flow(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )

    await repo.insert(
        conn,
        state=state,
        provider=_PROVIDER,
        payload={
            "name": name,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "folder_name": folder_name,
        },
        target_connection_id=target_connection_id,
        created_by_user_id=created_by_user_id,
        ttl_seconds=_TTL_SECONDS,
    )
    await audit_log_insert(
        conn,
        "remote_backup.gdrive.oauth_started",
        actor_user_id=created_by_user_id,
        metadata={
            "connection_name": name,
            "folder_name": folder_name,
            "target_connection_id": str(target_connection_id) if target_connection_id else None,
        },
    )
    return {"auth_url": auth_url, "state": state}


async def finalize_session(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    code: str,
) -> None:
    """Échange `code` contre des tokens, marque la session 'authorized' avec result."""
    pending = await repo.get_active_by_state(conn, state)
    if pending is None:
        raise OAuthSessionError("state_not_found_or_expired")

    payload = dict(pending["payload"])
    flow = gdrive_client.build_flow(
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        redirect_uri=payload["redirect_uri"],
    )
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise OAuthSessionError(f"token_exchange_failed: {exc}") from exc

    creds = flow.credentials
    refresh_token = getattr(creds, "refresh_token", None)
    if not refresh_token:
        raise OAuthSessionError("no_refresh_token_returned")

    try:
        user_email = gdrive_client.fetch_user_email(creds)
    except Exception as exc:
        _log.warning("gdrive_fetch_user_email_failed", extra={"err": str(exc)})
        user_email = ""

    await repo.mark_authorized(
        conn,
        state=state,
        result={
            "refresh_token": refresh_token,
            "user_email": user_email,
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    )
    await audit_log_insert(
        conn,
        "remote_backup.gdrive.oauth_completed",
        actor_user_id=None,
        metadata={
            "state": state,
            "user_email": user_email,
        },
    )


async def mark_session_failed(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    error: str,
) -> None:
    await repo.mark_failed(conn, state=state, error=error)
    await audit_log_insert(
        conn,
        "remote_backup.gdrive.oauth_failed",
        actor_user_id=None,
        metadata={"state": state, "error": error},
        success=False,
    )


def public_session_view(row: asyncpg.Record | dict[str, Any] | None) -> dict[str, Any]:
    """Vue publique d'une session — sans aucun secret. Pour GET /session/{state}.

    Accepte aussi un dict simple (utile pour les tests unitaires sans DB).
    """
    if row is None:
        return {"status": "unknown"}
    raw_result = row.get("result", None)
    result = dict(raw_result) if raw_result else {}
    safe_result: dict[str, Any] = {}
    if "user_email" in result:
        safe_result["user_email"] = result["user_email"]
    if "error" in result:
        safe_result["error"] = result["error"]
    return {
        "status": row["status"],
        "result": safe_result or None,
    }
