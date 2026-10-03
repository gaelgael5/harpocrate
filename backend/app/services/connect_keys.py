"""Création de l'API key scellée et émission du code (feature 4, décisions D3, D4, D9, D14).

Le serveur ne voit jamais la `dkey` de la clé créée par ce flux : il signe le token avec
le segment de substitution (le HMAC ne couvre pas la dkey), le navigateur y remet la vraie
dkey et scelle le tout pour la clé publique éphémère de l'application. Harpocrate ne
stocke que ce scellé, illisible pour lui, jusqu'à l'échange du code.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import secrets
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.core.api_key_token import DKEY_PLACEHOLDER, encode_token
from app.core.config import settings
from app.db.repositories import api_keys as api_keys_repo
from app.db.repositories import connect_requests as repo
from app.db.repositories import wallets as wallets_repo
from app.models.api.connect_flow import ConnectApiKeyCreate, ConnectApiKeyResponse
from app.services.audit import audit_log_insert
from app.services.connect_requests import lock_request_for_user, redirect_with
from app.services.permissions import PERM_SHARE, has, is_subset, to_names

# Durée de vie du code à usage unique (D9) : le temps d'une redirection et d'un appel
# serveur à serveur, pas davantage.
CODE_TTL_SECONDS = 60
_CODE_BYTES = 32


def _error(code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=code, detail={"error": error, "message": message})


def code_hash(code: str) -> bytes:
    """Empreinte stockée du code ; le code en clair ne touche jamais la base."""
    return hashlib.sha256(code.encode("ascii")).digest()


async def _user_permissions_on_wallet(
    conn: asyncpg.Connection[asyncpg.Record], wallet_id: UUID, user_id: UUID
) -> int:
    """Droits de l'utilisateur sur le wallet choisi ; [share] est exigé pour créer une clé,
    comme sur la page API keys. Un wallet supprimé (corbeille) n'est pas proposable."""
    wallet = await wallets_repo.get_wallet_for_user(conn, wallet_id=wallet_id, user_id=user_id)
    if wallet is None or wallet.deleted_at is not None:
        raise _error(404, "wallet_not_found", "Wallet not found")
    if not has(wallet.my_permissions, PERM_SHARE):
        raise _error(403, "missing_share_permission", "The [share] permission is required")
    return wallet.my_permissions


def _check_ttl(requested_ttl_days: int | None, ttl_days: int | None) -> None:
    # L'utilisateur peut seulement RÉDUIRE la durée demandée (D3) : une demande bornée
    # exige une durée, au plus celle demandée ; une demande sans expiration accepte tout.
    if requested_ttl_days is None:
        return
    if ttl_days is None or ttl_days > requested_ttl_days:
        raise _error(400, "ttl_exceeds_request", "API key lifetime exceeds the requested one")


async def create_connect_api_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    request_uri: str,
    client_id: str,
    body: ConnectApiKeyCreate,
    user_id: UUID,
    now: datetime.datetime,
    actor_ip: str | None,
) -> ConnectApiKeyResponse:
    """Crée la clé de la demande ; permissions ⊆ demandées ∩ droits de l'utilisateur."""
    async with conn.transaction():
        row = await lock_request_for_user(
            conn, request_uri=request_uri, client_id=client_id, user_id=user_id, now=now
        )
        if row.api_key_id is not None:
            raise _error(409, "api_key_already_created", "An API key was already created")
        caller_perms = await _user_permissions_on_wallet(conn, body.wallet_id, user_id)
        if not is_subset(body.permissions, row.requested_permissions & caller_perms):
            raise _error(
                400,
                "permissions_exceed_request",
                "API key permissions must stay within the request and your own rights",
            )
        _check_ttl(row.requested_ttl_days, body.ttl_days)
        expires_at = None if body.ttl_days is None else now + datetime.timedelta(days=body.ttl_days)
        api_key_id = await api_keys_repo.insert_api_key(
            conn,
            wallet_id=body.wallet_id,
            owner_user_id=user_id,
            name=row.client_name,
            description=None,
            auth_hash=base64.b64decode(body.auth_hash),
            auth_salt=base64.b64decode(body.auth_salt),
            auth_kdf_memory_kb=body.auth_kdf_memory_kb,
            auth_kdf_iterations=body.auth_kdf_iterations,
            auth_kdf_parallelism=body.auth_kdf_parallelism,
            encrypted_wallet_key=base64.b64decode(body.encrypted_wallet_key),
            encrypted_decryption_key_for_owner=base64.b64decode(
                body.encrypted_decryption_key_for_owner
            ),
            permissions=body.permissions,
            expires_at=expires_at,
            connect_client_id=row.client_pk,
        )
        await repo.db_attach_key(conn, row.id, wallet_id=body.wallet_id, api_key_id=api_key_id)
        await audit_log_insert(
            conn,
            "api_key.created",
            actor_user_id=user_id,
            actor_ip=actor_ip,
            target_wallet_id=body.wallet_id,
            target_api_key_id=api_key_id,
            metadata={
                "api_key_id": str(api_key_id),
                "name": row.client_name,
                "permissions": body.permissions,
                "permissions_names": to_names(body.permissions),
                "connect_client_id": row.client_id,
            },
        )
    token = encode_token(
        api_key_id=api_key_id,
        exp=0 if expires_at is None else int(expires_at.timestamp()),
        perms=body.permissions,
        auth_secret_b64=body.auth_secret,
        dkey_b64=DKEY_PLACEHOLDER,
        master_key_b64=settings.hmac_key,
    )
    return ConnectApiKeyResponse(api_key_id=api_key_id, token=token)


async def seal_request(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    request_uri: str,
    client_id: str,
    jwe: str,
    user_id: UUID,
    now: datetime.datetime,
    actor_ip: str | None,
) -> str:
    """Dépose le scellé, émet le code à usage unique ; renvoie l'URL de retour
    `redirect_uri?code&state` (le `state` revient inchangé, invariant 5)."""
    code = secrets.token_urlsafe(_CODE_BYTES)
    async with conn.transaction():
        row = await lock_request_for_user(
            conn, request_uri=request_uri, client_id=client_id, user_id=user_id, now=now
        )
        if row.api_key_id is None:
            raise _error(409, "api_key_missing", "Create the API key before sealing it")
        await repo.db_seal(
            conn,
            row.id,
            sealed_jwe=jwe,
            code_hash=code_hash(code),
            code_expires_at=now + datetime.timedelta(seconds=CODE_TTL_SECONDS),
        )
        await audit_log_insert(
            conn,
            "connect_request.approved",
            actor_user_id=user_id,
            actor_ip=actor_ip,
            target_wallet_id=row.wallet_id,
            target_api_key_id=row.api_key_id,
            metadata={"client_id": row.client_id},
        )
    return redirect_with(row.redirect_uri, {"code": code, "state": row.state})
