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

from app.models.db.connect_request import (
    ConnectRequestRow,
    ConnectRequestWithCode,
    UndeliveredKey,
)


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


async def db_set_status(
    conn: asyncpg.Connection[asyncpg.Record], request_id: UUID, status: str
) -> None:
    """Change l'état d'une demande (les valeurs admises sont garanties par un CHECK)."""
    await conn.execute(
        "UPDATE connect_requests SET status = $2 WHERE id = $1",
        request_id,
        status,
    )


async def db_attach_key(
    conn: asyncpg.Connection[asyncpg.Record],
    request_id: UUID,
    *,
    wallet_id: UUID,
    api_key_id: UUID,
) -> None:
    """Rattache à la demande le wallet choisi et la clé créée pour elle."""
    await conn.execute(
        "UPDATE connect_requests SET wallet_id = $2, api_key_id = $3 WHERE id = $1",
        request_id,
        wallet_id,
        api_key_id,
    )


async def db_seal(
    conn: asyncpg.Connection[asyncpg.Record],
    request_id: UUID,
    *,
    sealed_jwe: str,
    code_hash: bytes,
    code_expires_at: datetime.datetime,
) -> None:
    """Dépose le scellé et l'empreinte du code à usage unique (contrainte
    `connect_requests_sealed_complete` : les trois vont ensemble)."""
    await conn.execute(
        """
        UPDATE connect_requests
           SET status = 'sealed', sealed_jwe = $2, code_hash = $3, code_expires_at = $4
         WHERE id = $1
        """,
        request_id,
        sealed_jwe,
        code_hash,
        code_expires_at,
    )


async def db_get_by_code_hash_for_update(
    conn: asyncpg.Connection[asyncpg.Record], code_hash: bytes
) -> ConnectRequestWithCode | None:
    """Demande par empreinte du code, verrouillée : deux échanges concurrents du même
    code se sérialisent, le second voit la demande déjà livrée."""
    row = await conn.fetchrow(
        """
        SELECT r.id, r.client_pk, c.client_id, c.name AS client_name,
               c.description AS client_description, c.active AS client_active,
               r.redirect_uri, r.state, r.code_challenge, r.requested_permissions,
               r.requested_ttl_days, r.app_public_jwk, r.status, r.user_id,
               r.wallet_id, r.api_key_id, r.expires_at, r.created_at,
               r.sealed_jwe, r.code_expires_at
          FROM connect_requests r
          JOIN connect_clients c ON c.id = r.client_pk
         WHERE r.code_hash = $1
           FOR UPDATE OF r
        """,
        code_hash,
    )
    if row is None:
        return None
    base = _to_row(row)
    return ConnectRequestWithCode(
        **base.model_dump(),
        sealed_jwe=row["sealed_jwe"],
        code_expires_at=row["code_expires_at"],
    )


async def db_mark_delivered(conn: asyncpg.Connection[asyncpg.Record], request_id: UUID) -> None:
    """Scellé remis : il est effacé dans la même écriture (contrainte
    `connect_requests_delivered_erased`). L'empreinte du code reste, pour reconnaître un rejeu."""
    await conn.execute(
        "UPDATE connect_requests SET status = 'delivered', sealed_jwe = NULL WHERE id = $1",
        request_id,
    )


async def db_list_expired_undelivered_keys(
    conn: asyncpg.Connection[asyncpg.Record], now: datetime.datetime
) -> list[UndeliveredKey]:
    rows = await conn.fetch(
        """
        SELECT r.id AS request_id, r.api_key_id, r.wallet_id, c.client_id
          FROM connect_requests r
          JOIN connect_clients c ON c.id = r.client_pk
         WHERE r.expires_at <= $1
           AND r.status IN ('pending', 'sealed')
           AND r.api_key_id IS NOT NULL
           AND r.wallet_id IS NOT NULL
        """,
        now,
    )
    return [UndeliveredKey(**dict(r)) for r in rows]


async def db_delete_expired(
    conn: asyncpg.Connection[asyncpg.Record], now: datetime.datetime
) -> int:
    """Supprime les demandes arrivées à échéance, quel que soit leur état ; renvoie leur nombre."""
    result: str = await conn.execute(
        "DELETE FROM connect_requests WHERE expires_at <= $1",
        now,
    )
    return int(result.split()[-1])
