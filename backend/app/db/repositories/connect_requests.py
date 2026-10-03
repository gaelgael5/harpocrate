"""Requêtes SQL pour la table connect_requests — demandes de connexion (migration 033).

La référence opaque remise au navigateur n'est jamais stockée : seule son empreinte
SHA-256 (`request_ref_hash`) l'est, comme pour les jetons de ré-vérification.
Requêtes écrites en entier, sans construction par f-string.
"""

from __future__ import annotations

import datetime
import json
from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.connect_request import ConnectRequestRow


def _to_row(row: Any) -> ConnectRequestRow:
    jwk = row["app_public_jwk"]
    return ConnectRequestRow(
        id=row["id"],
        client_pk=row["client_pk"],
        client_id=row["client_id"],
        client_name=row["client_name"],
        client_description=row["client_description"],
        client_active=row["client_active"],
        redirect_uri=row["redirect_uri"],
        state=row["state"],
        code_challenge=row["code_challenge"],
        requested_permissions=row["requested_permissions"],
        requested_ttl_days=row["requested_ttl_days"],
        # asyncpg rend le JSONB en texte faute de codec enregistré sur la connexion.
        app_public_jwk=json.loads(jwk) if isinstance(jwk, str) else dict(jwk),
        status=row["status"],
        user_id=row["user_id"],
        wallet_id=row["wallet_id"],
        api_key_id=row["api_key_id"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )


async def db_insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    request_ref_hash: bytes,
    client_pk: UUID,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    requested_permissions: int,
    requested_ttl_days: int | None,
    app_public_jwk: dict[str, Any],
    expires_at: datetime.datetime,
) -> UUID:
    """Insère une demande en attente et renvoie son identifiant interne."""
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO connect_requests
            (request_ref_hash, client_pk, redirect_uri, state, code_challenge,
             requested_permissions, requested_ttl_days, app_public_jwk, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
        RETURNING id
        """,
        request_ref_hash,
        client_pk,
        redirect_uri,
        state,
        code_challenge,
        requested_permissions,
        requested_ttl_days,
        json.dumps(app_public_jwk),
        expires_at,
    )
    return new_id


async def db_get_by_ref_hash(
    conn: asyncpg.Connection[asyncpg.Record],
    request_ref_hash: bytes,
    *,
    for_update: bool = False,
) -> ConnectRequestRow | None:
    """Demande et application associée, par empreinte de la référence opaque.

    `for_update` verrouille la ligne de la demande (pas celle de l'application) : chaque
    transition d'état (prise en charge, refus, scellement) la lit puis la réécrit.
    """
    if for_update:
        row = await conn.fetchrow(
            """
            SELECT r.id, r.client_pk, c.client_id, c.name AS client_name,
                   c.description AS client_description, c.active AS client_active,
                   r.redirect_uri, r.state, r.code_challenge, r.requested_permissions,
                   r.requested_ttl_days, r.app_public_jwk, r.status, r.user_id,
                   r.wallet_id, r.api_key_id, r.expires_at, r.created_at
              FROM connect_requests r
              JOIN connect_clients c ON c.id = r.client_pk
             WHERE r.request_ref_hash = $1
               FOR UPDATE OF r
            """,
            request_ref_hash,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT r.id, r.client_pk, c.client_id, c.name AS client_name,
                   c.description AS client_description, c.active AS client_active,
                   r.redirect_uri, r.state, r.code_challenge, r.requested_permissions,
                   r.requested_ttl_days, r.app_public_jwk, r.status, r.user_id,
                   r.wallet_id, r.api_key_id, r.expires_at, r.created_at
              FROM connect_requests r
              JOIN connect_clients c ON c.id = r.client_pk
             WHERE r.request_ref_hash = $1
            """,
            request_ref_hash,
        )
    return _to_row(row) if row else None


async def db_claim(
    conn: asyncpg.Connection[asyncpg.Record], request_id: UUID, user_id: UUID
) -> bool:
    """Rattache la demande au premier utilisateur qui l'ouvre.

    Renvoie False si elle était déjà rattachée (à quiconque) : la condition `user_id IS
    NULL` dans l'UPDATE tranche entre deux ouvertures concurrentes.
    """
    result: str = await conn.execute(
        """
        UPDATE connect_requests
           SET user_id = $2
         WHERE id = $1 AND user_id IS NULL
        """,
        request_id,
        user_id,
    )
    return result == "UPDATE 1"
