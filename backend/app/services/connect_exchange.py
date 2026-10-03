"""Échange du code par le backend de l'application, et purge (feature 5, D2, D7, D13).

L'application n'est pas authentifiée (D7) : ce qui en tient lieu, c'est que le code n'est
parti que vers une URL déclarée, que PKCE S256 le lie à l'instance qui a déposé la demande,
et que le scellé n'est lisible qu'avec sa clé privée éphémère. Le scellé est remis UNE fois,
puis effacé ; une seconde présentation du code est une anomalie, journalisée comme telle.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac

import asyncpg
import structlog
from fastapi import HTTPException

from app.core import api_key_cache
from app.db.repositories import api_keys as api_keys_repo
from app.db.repositories import connect_requests as repo
from app.models.api.connect_flow import ConnectTokenRequest, ConnectTokenResponse
from app.models.db.connect_request import ConnectRequestWithCode
from app.services import system_anomalies
from app.services.audit import audit_log_insert
from app.services.connect_keys import code_hash

logger = structlog.get_logger(__name__)


def _invalid_grant() -> HTTPException:
    # Une seule réponse pour toutes les causes de refus (RFC 6749 §5.2) : rien n'indique à
    # qui essaie des codes lequel de ses paramètres était faux.
    return HTTPException(
        status_code=400,
        detail={"error": "invalid_grant", "message": "Invalid, expired or already used code"},
    )


def pkce_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _record_rejection(
    conn: asyncpg.Connection[asyncpg.Record],
    row: ConnectRequestWithCode,
    action: str,
    actor_ip: str | None,
) -> None:
    """Trace un échange refusé sur un code CONNU (rejeu, expiration, PKCE…).

    Écrit HORS de la transaction de l'échange, qui est annulée par le refus : sinon la
    trace disparaîtrait avec elle. Un rejeu est en plus une anomalie, visible des admins.
    """
    await audit_log_insert(
        conn,
        action,
        actor_ip=actor_ip,
        target_api_key_id=row.api_key_id,
        metadata={"client_id": row.client_id},
        success=False,
        error_code="invalid_grant",
    )
    if action == "connect_code.replayed":
        await system_anomalies.report(
            conn,
            severity="warning",
            anomaly_type="connect_code_replayed",
            source="connect",
            source_ref_id=row.api_key_id,
            message=f"Connect code presented again after delivery (client {row.client_id})",
            metadata={"client_id": row.client_id, "actor_ip": actor_ip},
        )
    logger.warning("connect_code_rejected", reason=action, client_id=row.client_id)


def _rejection(
    row: ConnectRequestWithCode, body: ConnectTokenRequest, now: datetime.datetime
) -> str | None:
    """Motif d'audit du refus, ou None si l'échange est valide."""
    if row.status == "delivered":
        return "connect_code.replayed"
    if row.status != "sealed" or row.code_expires_at is None or row.code_expires_at <= now:
        return "connect_code.expired"
    if row.client_id != body.client_id or row.redirect_uri != body.redirect_uri:
        return "connect_code.client_mismatch"
    if not hmac.compare_digest(pkce_s256(body.code_verifier), row.code_challenge):
        return "connect_code.pkce_failed"
    return None


async def _deliver(
    conn: asyncpg.Connection[asyncpg.Record],
    body: ConnectTokenRequest,
    now: datetime.datetime,
    actor_ip: str | None,
) -> tuple[ConnectRequestWithCode | None, str | None]:
    """Livre le scellé si le code est valide. Renvoie (demande, motif de refus)."""
    async with conn.transaction():
        row = await repo.db_get_by_code_hash_for_update(conn, code_hash(body.code))
        if row is None:
            return None, "unknown"
        reason = _rejection(row, body, now)
        if reason is not None:
            return row, reason
        await repo.db_mark_delivered(conn, row.id)
        await audit_log_insert(
            conn,
            "connect_code.exchanged",
            actor_ip=actor_ip,
            target_wallet_id=row.wallet_id,
            target_api_key_id=row.api_key_id,
            metadata={"client_id": row.client_id},
        )
    return row, None


async def exchange_code(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    body: ConnectTokenRequest,
    now: datetime.datetime,
    actor_ip: str | None,
) -> ConnectTokenResponse:
    row, reason = await _deliver(conn, body, now, actor_ip)
    if row is None:
        raise _invalid_grant()
    if reason is not None:
        await _record_rejection(conn, row, reason, actor_ip)
        raise _invalid_grant()
    # Garantis par la contrainte connect_requests_sealed_complete et par le scellement.
    if row.sealed_jwe is None or row.api_key_id is None or row.wallet_id is None:
        raise _invalid_grant()
    return ConnectTokenResponse(
        jwe=row.sealed_jwe, api_key_id=row.api_key_id, wallet_id=row.wallet_id
    )


async def purge_expired_requests(
    conn: asyncpg.Connection[asyncpg.Record], *, now: datetime.datetime
) -> int:
    """Révoque les clés jamais livrées (D13), puis supprime les demandes échues.

    Une clé créée mais jamais remise à l'application (onglet fermé, application en panne)
    n'est détenue par personne : elle ne doit pas rester active.
    """
    async with conn.transaction():
        for key in await repo.db_list_expired_undelivered_keys(conn, now):
            revoked = await api_keys_repo.revoke_api_key(
                conn, api_key_id=key.api_key_id, wallet_id=key.wallet_id
            )
            if revoked:
                api_key_cache.cache_invalidate(key.api_key_id)
                await audit_log_insert(
                    conn,
                    "api_key.revoked",
                    target_wallet_id=key.wallet_id,
                    target_api_key_id=key.api_key_id,
                    metadata={"reason": "connect_not_delivered", "client_id": key.client_id},
                )
        return await repo.db_delete_expired(conn, now)
