"""Requêtes SQL pour la table users."""
from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.user import UserRow


def _row_to_user(row: Any) -> UserRow:
    return UserRow(
        id=row["id"],
        keycloak_sub=row["keycloak_sub"],
        email=row["email"],
        display_name=row["display_name"],
        rsa_public_key=bytes(row["rsa_public_key"]),
        salt_passphrase=bytes(row["salt_passphrase"]),
        salt_recovery=bytes(row["salt_recovery"]),
        encrypted_rsa_private_key=bytes(row["encrypted_rsa_private_key"]),
        encrypted_sym_key_by_pass=bytes(row["encrypted_sym_key_by_pass"]),
        encrypted_sym_key_by_recovery=bytes(row["encrypted_sym_key_by_recovery"]),
        kdf_memory_kb=row["kdf_memory_kb"],
        kdf_iterations=row["kdf_iterations"],
        kdf_parallelism=row["kdf_parallelism"],
        rsa_key_size=row["rsa_key_size"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_unlock_at=row["last_unlock_at"],
        quarantine_until=row.get("quarantine_until", None),
        quarantine_reason=row.get("quarantine_reason", None),
        force_reverify_next_login=row.get("force_reverify_next_login", False),
        disabled_at=row.get("disabled_at", None),
        disabled_reason=row.get("disabled_reason", None),
    )


async def get_by_keycloak_sub(
    conn: asyncpg.Connection[asyncpg.Record],
    sub: str,
) -> UserRow | None:
    """Retourne l'utilisateur par son keycloak_sub, ou None."""
    row = await conn.fetchrow(
        "SELECT * FROM users WHERE keycloak_sub = $1",
        sub,
    )
    return _row_to_user(row) if row else None


async def insert_bootstrap(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    keycloak_sub: str,
    email: str,
    display_name: str | None,
    rsa_public_key: bytes,
    salt_passphrase: bytes,
    salt_recovery: bytes,
    encrypted_rsa_private_key: bytes,
    encrypted_sym_key_by_pass: bytes,
    encrypted_sym_key_by_recovery: bytes,
    kdf_memory_kb: int,
    kdf_iterations: int,
    kdf_parallelism: int,
    rsa_key_size: int,
) -> UUID:
    """Insère un utilisateur bootstrappé et retourne son UUID."""
    result: UUID = await conn.fetchval(
        """
        INSERT INTO users (
            keycloak_sub, email, display_name,
            rsa_public_key, salt_passphrase, salt_recovery,
            encrypted_rsa_private_key, encrypted_sym_key_by_pass,
            encrypted_sym_key_by_recovery,
            kdf_memory_kb, kdf_iterations, kdf_parallelism, rsa_key_size
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        RETURNING id
        """,
        keycloak_sub,
        email,
        display_name,
        rsa_public_key,
        salt_passphrase,
        salt_recovery,
        encrypted_rsa_private_key,
        encrypted_sym_key_by_pass,
        encrypted_sym_key_by_recovery,
        kdf_memory_kb,
        kdf_iterations,
        kdf_parallelism,
        rsa_key_size,
    )
    return result


async def update_passphrase(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
    new_salt_passphrase: bytes,
    new_encrypted_rsa_private_key: bytes,
    new_encrypted_sym_key_by_pass: bytes,
    kdf_memory_kb: int,
    kdf_iterations: int,
    kdf_parallelism: int,
) -> datetime.datetime:
    """Met à jour les blobs passphrase et retourne le updated_at."""
    result: datetime.datetime = await conn.fetchval(
        """
        UPDATE users
        SET
            salt_passphrase = $2,
            encrypted_rsa_private_key = $3,
            encrypted_sym_key_by_pass = $4,
            kdf_memory_kb = $5,
            kdf_iterations = $6,
            kdf_parallelism = $7
        WHERE id = $1
        RETURNING updated_at
        """,
        user_id,
        new_salt_passphrase,
        new_encrypted_rsa_private_key,
        new_encrypted_sym_key_by_pass,
        kdf_memory_kb,
        kdf_iterations,
        kdf_parallelism,
    )
    return result


async def update_recovery(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
    new_salt_recovery: bytes,
    new_encrypted_sym_key_by_recovery: bytes,
) -> datetime.datetime:
    """Met à jour le blob recovery et retourne le updated_at."""
    result: datetime.datetime = await conn.fetchval(
        """
        UPDATE users
        SET
            salt_recovery = $2,
            encrypted_sym_key_by_recovery = $3
        WHERE id = $1
        RETURNING updated_at
        """,
        user_id,
        new_salt_recovery,
        new_encrypted_sym_key_by_recovery,
    )
    return result


async def get_crypto(
    conn: asyncpg.Connection[asyncpg.Record],
    sub: str,
) -> UserRow | None:
    """Récupère les blobs crypto d'un utilisateur par son sub."""
    row = await conn.fetchrow(
        """
        SELECT * FROM users WHERE keycloak_sub = $1
        """,
        sub,
    )
    return _row_to_user(row) if row else None


async def touch_last_unlock(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
) -> None:
    """Met à jour last_unlock_at à maintenant."""
    await conn.execute(
        "UPDATE users SET last_unlock_at = NOW() WHERE id = $1",
        user_id,
    )


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    user_id: UUID,
) -> UserRow | None:
    """Retourne l'utilisateur par son UUID interne, ou None."""
    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return _row_to_user(row) if row else None


async def clear_quarantine(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
) -> None:
    """Lève la quarantaine et réinitialise force_reverify_next_login."""
    await conn.execute(
        """
        UPDATE users
        SET quarantine_until = NULL,
            quarantine_reason = NULL,
            force_reverify_next_login = FALSE
        WHERE id = $1
        """,
        user_id,
    )


async def set_email(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
    email: str,
) -> None:
    """Met à jour l'email de l'utilisateur."""
    await conn.execute(
        "UPDATE users SET email = $2 WHERE id = $1",
        user_id,
        email,
    )
