"""Aides partagées par les tests du flux « Se connecter avec Harpocrate » (features 2 à 5).

Toutes travaillent sur une vraie base (``HARPOCRATE_DB_DSN_TEST``), dans une transaction
annulée à la fin de chaque test.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import secrets
import uuid
from typing import Any, cast
from uuid import UUID

import asyncpg
from cryptography.hazmat.primitives.asymmetric import ec

from app.db.repositories import connect_clients as clients_repo
from app.models.api.connect_flow import ConnectParRequest
from app.models.db.connect_client import ConnectClientRow

REDIRECT_URI = "https://rag.example/harpocrate/callback"
NOW = datetime.datetime(2026, 10, 3, 12, 0, tzinfo=datetime.UTC)


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_jwk() -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    """Paire de clés éphémère P-256 de l'application, et sa clé publique en JWK."""
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(numbers.x.to_bytes(32, "big")),
        "y": b64url(numbers.y.to_bytes(32, "big")),
    }
    return private, jwk


def make_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge S256)."""
    verifier = b64url(secrets.token_bytes(32))
    return verifier, b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def par_body(client_id: str = "ragflow", **overrides: Any) -> ConnectParRequest:
    _, jwk = make_jwk()
    _, challenge = make_pkce()
    fields: dict[str, Any] = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": "st-" + secrets.token_hex(8),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "permissions": 0x01 | 0x02,
        "ttl_days": 90,
        "app_public_jwk": jwk,
    }
    fields.update(overrides)
    return ConnectParRequest.model_validate(fields)


async def insert_user(conn: asyncpg.Connection[asyncpg.Record]) -> UUID:
    return cast(
        UUID,
        await conn.fetchval(
            """
            INSERT INTO users (
                keycloak_sub, email, rsa_public_key,
                salt_passphrase, salt_recovery,
                encrypted_rsa_private_key, encrypted_sym_key_by_pass,
                encrypted_sym_key_by_recovery,
                kdf_memory_kb, kdf_iterations, kdf_parallelism, rsa_key_size
            ) VALUES (
                $1, $2, '\\x00', '\\x00', '\\x00',
                '\\x00', '\\x00', '\\x00',
                65536, 3, 4, 2048
            ) RETURNING id
            """,
            f"sub-{uuid.uuid4()}",
            f"test-{uuid.uuid4()}@example.com",
        ),
    )


async def insert_client(
    conn: asyncpg.Connection[asyncpg.Record], client_id: str = "ragflow"
) -> ConnectClientRow:
    return await clients_repo.db_insert(
        conn,
        client_id=client_id,
        name="Ragflow (déclaré)",
        description="Moteur RAG",
        redirect_uris=[REDIRECT_URI],
        created_by_user_id=None,
    )


def par_body_with_verifier(**overrides: Any) -> tuple[ConnectParRequest, str]:
    """Demande PAR et son `code_verifier`, pour aller jusqu'à l'échange du code."""
    verifier, challenge = make_pkce()
    return par_body(code_challenge=challenge, **overrides), verifier


async def insert_wallet(
    conn: asyncpg.Connection[asyncpg.Record], user_id: UUID, permissions: int = 0x3F
) -> UUID:
    """Wallet dont `user_id` est propriétaire, avec un grant portant `permissions`."""
    wallet_id = cast(
        UUID,
        await conn.fetchval(
            "INSERT INTO wallets (name, owner_user_id) VALUES ($1, $2) RETURNING id",
            f"wallet-{uuid.uuid4()}",
            user_id,
        ),
    )
    await conn.execute(
        """
        INSERT INTO wallet_grants
            (wallet_id, grantee_user_id, encrypted_wallet_key, permissions, granted_by_user_id)
        VALUES ($1, $2, '\\x00', $3, $2)
        """,
        wallet_id,
        user_id,
        permissions,
    )
    return wallet_id


def api_key_body(wallet_id: UUID, permissions: int = 0x01, ttl_days: int | None = 30) -> Any:
    """Corps de création de clé tel que l'enverrait le navigateur — SANS dkey."""
    from app.core.config import settings
    from app.models.api.connect_flow import ConnectApiKeyCreate

    return ConnectApiKeyCreate.model_validate(
        {
            "wallet_id": str(wallet_id),
            "permissions": permissions,
            "ttl_days": ttl_days,
            "auth_secret": b64url(secrets.token_bytes(32)),
            "auth_hash": base64.b64encode(b"$argon2id$fake").decode(),
            "auth_salt": base64.b64encode(secrets.token_bytes(16)).decode(),
            "auth_kdf_memory_kb": settings.kdf_memory_kb,
            "auth_kdf_iterations": settings.kdf_iterations,
            "auth_kdf_parallelism": settings.kdf_parallelism,
            "encrypted_wallet_key": base64.b64encode(b"enc-wallet-key").decode(),
            "encrypted_decryption_key_for_owner": base64.b64encode(b"enc-dkey").decode(),
        }
    )


def fake_jwe() -> str:
    """JWE compact de la bonne forme (en-tête ECDH-ES / A256GCM) ; le serveur ne le lit pas."""
    import json

    _, jwk = make_jwk()
    header = {"alg": "ECDH-ES", "enc": "A256GCM", "epk": jwk}
    protected = b64url(json.dumps(header).encode())
    iv, tag = b64url(secrets.token_bytes(12)), b64url(secrets.token_bytes(16))
    return f"{protected}..{iv}.{b64url(b'ciphertext')}.{tag}"
