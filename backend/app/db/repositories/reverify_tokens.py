"""Repository pour reverify_tokens (LOT_02 governance).

Tokens one-shot, expires apres 5 min, demandes pour les actions sensibles
(changer passphrase, renouveler recovery, supprimer un wallet).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from app.models.db.identity import ReverifyTokenRow

REVERIFY_TTL_SECONDS = 5 * 60  # 5 min


def _hash_token(token: str) -> bytes:
    """SHA-256 du token cote application (constant-time pas necessaire pour
    la comparaison hash, fait par le storage du hash en BYTEA)."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def generate_token() -> tuple[str, bytes]:
    """Genere un token aleatoire (32 bytes base64url) et son hash SHA-256."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash_token(raw)


async def insert(
    conn: asyncpg.Connection,
    user_id: UUID,
    token_hash: bytes,
    ttl_seconds: int = REVERIFY_TTL_SECONDS,
) -> UUID:
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO reverify_tokens (user_id, token_hash, expires_at)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        user_id,
        token_hash,
        expires_at,
    )
    return new_id


async def consume(
    conn: asyncpg.Connection, user_id: UUID, token: str
) -> ReverifyTokenRow | None:
    """Cherche et marque consomme atomiquement. Retourne le row si valide
    (existe, pas expire, pas deja consomme), sinon None.
    Le token est passe en clair par le client, on hash et on compare."""
    token_hash = _hash_token(token)
    row = await conn.fetchrow(
        """
        UPDATE reverify_tokens
        SET consumed_at = NOW()
        WHERE user_id = $1
          AND token_hash = $2
          AND consumed_at IS NULL
          AND expires_at > NOW()
        RETURNING *
        """,
        user_id,
        token_hash,
    )
    return ReverifyTokenRow(**dict(row)) if row else None


async def cleanup_expired(conn: asyncpg.Connection) -> int:
    """Supprime les tokens expires depuis plus d'un jour. Retourne le nombre
    supprime. A appeler depuis un cron (script de purge)."""
    result = await conn.execute(
        "DELETE FROM reverify_tokens "
        "WHERE expires_at < NOW() - INTERVAL '1 day'"
    )
    parts = str(result).split()
    return int(parts[1]) if len(parts) >= 2 and parts[0] == "DELETE" else 0
