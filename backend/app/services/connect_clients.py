"""Registre des applications autorisées à demander une connexion (feature 1, décision D1).

Seule une application déclarée ici, avec ses URLs de retour EXACTES, peut lancer le flux
« Se connecter avec Harpocrate ». C'est ce qui empêche une page tierce d'obtenir une API key
en se faisant passer pour une application connue (redirection ouverte, hameçonnage).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.db.repositories import connect_clients as repo
from app.models.db.connect_client import ConnectClientRow
from app.services.audit import audit_log_insert

MAX_REDIRECT_URI_LENGTH = 2048
# HTTP en clair n'est accepté que vers le poste local (application en développement) :
# partout ailleurs, le code à usage unique transiterait en clair sur le réseau.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class InvalidRedirectUriError(ValueError):
    """URL de retour refusée à la déclaration (ValueError : Pydantic la rend en 422)."""


def validate_redirect_uri(uri: str) -> str:
    """Valide une URL de retour et la renvoie telle quelle (elle sera comparée à l'identique)."""
    if not uri or len(uri) > MAX_REDIRECT_URI_LENGTH:
        raise InvalidRedirectUriError("redirect_uri is empty or too long")
    # Pas de joker : la comparaison est exacte, un motif ouvrirait la porte à tout sous-domaine.
    if "*" in uri or any(c.isspace() for c in uri):
        raise InvalidRedirectUriError("redirect_uri must not contain wildcards or spaces")
    parts = urlsplit(uri)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise InvalidRedirectUriError("redirect_uri must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise InvalidRedirectUriError("redirect_uri must not embed credentials")
    if "#" in uri:
        raise InvalidRedirectUriError("redirect_uri must not contain a fragment")
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        raise InvalidRedirectUriError("plain http is only allowed for localhost")
    try:
        _ = parts.port
    except ValueError as exc:
        raise InvalidRedirectUriError("redirect_uri has an invalid port") from exc
    return uri


def normalize_redirect_uris(uris: list[str]) -> list[str]:
    """Valide chaque URL et retire les doublons en gardant l'ordre de déclaration."""
    seen: dict[str, None] = {}
    for uri in uris:
        seen.setdefault(validate_redirect_uri(uri), None)
    return list(seen)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "connect_client_not_found", "message": "Connect client not found"},
    )


async def create_client(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    client_id: str,
    name: str,
    description: str | None,
    redirect_uris: list[str],
    actor_user_id: UUID,
    actor_ip: str | None,
) -> ConnectClientRow:
    async with conn.transaction():
        try:
            row = await repo.db_insert(
                conn,
                client_id=client_id,
                name=name,
                description=description,
                redirect_uris=redirect_uris,
                created_by_user_id=actor_user_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "client_id_taken",
                    "message": "This client_id is already declared",
                },
            ) from exc
        await audit_log_insert(
            conn,
            "connect_client.created",
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            metadata={"client_id": row.client_id, "redirect_uris_count": len(row.redirect_uris)},
        )
    return row


async def list_clients(conn: asyncpg.Connection[asyncpg.Record]) -> list[ConnectClientRow]:
    return await repo.db_list(conn)


async def get_client(conn: asyncpg.Connection[asyncpg.Record], client_pk: UUID) -> ConnectClientRow:
    row = await repo.db_get_by_id(conn, client_pk)
    if row is None:
        raise _not_found()
    return row


def _audit_action(current: ConnectClientRow, changes: dict[str, Any]) -> str:
    if "active" in changes and changes["active"] != current.active:
        return "connect_client.enabled" if changes["active"] else "connect_client.disabled"
    return "connect_client.updated"


async def update_client(
    conn: asyncpg.Connection[asyncpg.Record],
    client_pk: UUID,
    *,
    changes: dict[str, Any],
    actor_user_id: UUID,
    actor_ip: str | None,
) -> ConnectClientRow:
    """Applique une modification partielle (`changes` ne contient que les champs fournis)."""
    async with conn.transaction():
        current = await repo.db_get_by_id(conn, client_pk, for_update=True)
        if current is None:
            raise _not_found()
        merged = {
            "name": changes.get("name", current.name),
            "description": changes.get("description", current.description),
            "redirect_uris": changes.get("redirect_uris", current.redirect_uris),
            "active": changes.get("active", current.active),
        }
        changed = sorted(f for f, v in merged.items() if v != getattr(current, f))
        if not changed:
            return current
        updated = await repo.db_update(conn, client_pk, **merged)
        if updated is None:
            raise _not_found()
        await audit_log_insert(
            conn,
            _audit_action(current, changes),
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            metadata={"client_id": current.client_id, "changed": changed},
        )
    return updated
