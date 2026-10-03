"""Demandes de connexion « Se connecter avec Harpocrate » (feature 2, décisions D6, D7, D9).

Le backend d'une application déclarée dépose sa demande (PAR, RFC 9126) et reçoit une
référence opaque ; le navigateur ne porte que cette référence. Toute la validation a lieu
AU DÉPÔT, avant qu'aucune redirection ne soit possible : une URL de retour qui n'est pas
exactement déclarée n'atteint jamais le navigateur (invariant 1 du cadrage).
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.db.repositories import connect_clients as clients_repo
from app.db.repositories import connect_requests as repo
from app.models.api.connect_flow import REQUEST_URI_PREFIX, ConnectParRequest
from app.models.db.connect_request import ConnectRequestRow
from app.services.audit import audit_log_insert

# Durée de vie d'une demande en attente (D9) : alignée sur le verrouillage d'inactivité,
# elle laisse le temps de s'authentifier et de déverrouiller.
PENDING_TTL_SECONDS = 15 * 60
_REF_BYTES = 32


def _error(code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=code, detail={"error": error, "message": message})


def first_login_required() -> HTTPException:
    """Compte Keycloak connu mais jamais initialisé : le navigateur passe par /first-login."""
    return _error(404, "first_login", "User must bootstrap first")


def ref_hash(request_uri: str) -> bytes:
    """Empreinte stockée d'une référence ; seule l'empreinte touche la base."""
    return hashlib.sha256(request_uri.encode("ascii")).digest()


def _new_request_uri() -> str:
    return REQUEST_URI_PREFIX + secrets.token_urlsafe(_REF_BYTES)


async def create_request(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    body: ConnectParRequest,
    now: datetime.datetime,
    actor_ip: str | None,
) -> str:
    """Valide et enregistre une demande ; renvoie la référence opaque (`request_uri`).

    Pas d'authentification de l'application (D7) : seul compte que `client_id` soit une
    application active et que `redirect_uri` soit EXACTEMENT l'une de ses URLs déclarées.
    """
    client = await clients_repo.db_get_active_by_client_id(conn, body.client_id)
    if client is None:
        raise _error(400, "invalid_client", "Unknown or disabled client_id")
    # Comparaison exacte, sans normalisation : une variante (slash final, casse, port)
    # est une autre URL, donc refusée.
    if body.redirect_uri not in client.redirect_uris:
        raise _error(400, "invalid_redirect_uri", "redirect_uri is not declared for this client")
    request_uri = _new_request_uri()
    async with conn.transaction():
        await repo.db_insert(
            conn,
            request_ref_hash=ref_hash(request_uri),
            client_pk=client.id,
            redirect_uri=body.redirect_uri,
            state=body.state,
            code_challenge=body.code_challenge,
            requested_permissions=body.permissions,
            requested_ttl_days=body.ttl_days,
            app_public_jwk=body.app_public_jwk.model_dump(exclude_none=True),
            expires_at=now + datetime.timedelta(seconds=PENDING_TTL_SECONDS),
        )
        await audit_log_insert(
            conn,
            "connect_request.received",
            actor_ip=actor_ip,
            metadata={"client_id": client.client_id, "permissions": body.permissions},
        )
    return request_uri


def _check_usable(
    row: ConnectRequestRow | None, client_id: str, now: datetime.datetime
) -> ConnectRequestRow:
    # Référence inconnue, application désactivée depuis le dépôt, ou référence présentée
    # avec l'identifiant d'une AUTRE application : même réponse, rien n'est révélé.
    if row is None or not row.client_active or row.client_id != client_id:
        raise _error(404, "request_not_found", "Connect request not found")
    if row.status == "expired" or row.expires_at <= now:
        raise _error(410, "request_expired", "Connect request has expired")
    if row.status != "pending":
        raise _error(409, "request_not_pending", "Connect request was already answered")
    return row


async def open_request(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    request_uri: str,
    client_id: str,
    user_id: UUID,
    now: datetime.datetime,
) -> ConnectRequestRow:
    """Ouvre une demande en attente pour l'utilisateur connecté.

    Le premier utilisateur qui l'ouvre se l'approprie : une référence fuitée (journal,
    historique) ne permet pas à un autre compte de répondre à sa place.
    """
    async with conn.transaction():
        row = _check_usable(
            await repo.db_get_by_ref_hash(conn, ref_hash(request_uri), for_update=True),
            client_id,
            now,
        )
        if row.user_id is None:
            await repo.db_claim(conn, row.id, user_id)
            return row.model_copy(update={"user_id": user_id})
        if row.user_id != user_id:
            raise _error(404, "request_not_found", "Connect request not found")
    return row
