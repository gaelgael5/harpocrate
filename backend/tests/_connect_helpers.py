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
