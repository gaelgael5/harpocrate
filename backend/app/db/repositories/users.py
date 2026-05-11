"""Requêtes SQL pour la table users."""
from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.user import UserRow


def _row_to_user(row: Any) -> UserRow:
    enc_rsa_priv_by_recovery_raw = row.get("encrypted_rsa_private_key_by_recovery", None)
    enc_rsa_priv_by_recovery = (
        bytes(enc_rsa_priv_by_recovery_raw)
        if enc_rsa_priv_by_recovery_raw is not None
        else None
    )
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
        encrypted_rsa_private_key_by_recovery=enc_rsa_priv_by_recovery,
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
    """Retourne l'utilisateur par son keycloak_sub, ou None.

    Filtre les rows shell `is_system=TRUE` : elles n'ont pas de matériel
    crypto (rsa_public_key, salts, etc. = NULL), donc `_row_to_user`
    crasherait sur `bytes(None)`. Une row shell signifie "user pas encore
    bootstrappé" — du point de vue de `get_me`, équivalent à inexistant
    (le caller renvoie alors 404 first_login → l'UI route vers le
    bootstrap, qui fera `convert_system_user_to_real`).
    """
    row = await conn.fetchrow(
        "SELECT * FROM users WHERE keycloak_sub = $1 AND is_system = FALSE",
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
    encrypted_rsa_private_key_by_recovery: bytes,
    kdf_memory_kb: int,
    kdf_iterations: int,
    kdf_parallelism: int,
    rsa_key_size: int,
) -> UUID:
    """Insère un utilisateur bootstrappé et retourne son UUID.

    `encrypted_rsa_private_key_by_recovery` (LOT_57 fix) : permet la
    récupération zero-knowledge de rsa_priv via les 24 mots. Indispensable
    pour que le flow recovery soit fonctionnel — sans ça, l'utilisateur
    récupère seulement sym_key et se retrouve avec une rsa_priv inaccessible.
    """
    result: UUID = await conn.fetchval(
        """
        INSERT INTO users (
            keycloak_sub, email, display_name,
            rsa_public_key, salt_passphrase, salt_recovery,
            encrypted_rsa_private_key, encrypted_sym_key_by_pass,
            encrypted_sym_key_by_recovery,
            encrypted_rsa_private_key_by_recovery,
            kdf_memory_kb, kdf_iterations, kdf_parallelism, rsa_key_size
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
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
        encrypted_rsa_private_key_by_recovery,
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
    new_encrypted_rsa_private_key_by_recovery: bytes,
) -> datetime.datetime:
    """Met à jour le blob recovery et retourne le updated_at.

    LOT_57 fix : on doit aussi re-chiffrer rsa_priv avec la nouvelle
    recovery_key (sinon le flow recovery resterait inopérant après un
    renew_recovery — l'ancien blob by_recovery utiliserait l'ancienne
    recovery_key alors que les 24 mots ont changé).
    """
    result: datetime.datetime = await conn.fetchval(
        """
        UPDATE users
        SET
            salt_recovery = $2,
            encrypted_sym_key_by_recovery = $3,
            encrypted_rsa_private_key_by_recovery = $4
        WHERE id = $1
        RETURNING updated_at
        """,
        user_id,
        new_salt_recovery,
        new_encrypted_sym_key_by_recovery,
        new_encrypted_rsa_private_key_by_recovery,
    )
    return result


async def get_crypto(
    conn: asyncpg.Connection[asyncpg.Record],
    sub: str,
) -> UserRow | None:
    """Récupère les blobs crypto d'un utilisateur par son sub.

    Filtre `is_system=FALSE` pour la même raison que `get_by_keycloak_sub` :
    une row shell n'a pas de matériel crypto et `_row_to_user` planterait
    sur `bytes(None)`. Le caller (typiquement `/v1/me/crypto`) renverra
    alors 404 first_login.
    """
    row = await conn.fetchrow(
        """
        SELECT * FROM users WHERE keycloak_sub = $1 AND is_system = FALSE
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


# ─── System users (LOT_56 — admin local + Keycloak admins pré-bootstrap) ─────


async def get_id_by_keycloak_sub(
    conn: asyncpg.Connection[asyncpg.Record],
    sub: str,
) -> UUID | None:
    """Retourne uniquement l'UUID. Sûr pour les system users (lit pas le crypto)."""
    return await conn.fetchval(
        "SELECT id FROM users WHERE keycloak_sub = $1",
        sub,
    )


async def get_id_and_is_system_by_email(
    conn: asyncpg.Connection[asyncpg.Record],
    email: str,
) -> tuple[UUID, bool] | None:
    """Retourne (id, is_system) pour le user avec cet email, ou None."""
    row = await conn.fetchrow(
        "SELECT id, is_system FROM users WHERE email = $1",
        email,
    )
    if row is None:
        return None
    return row["id"], row["is_system"]


async def insert_system_user(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    keycloak_sub: str | None,
    email: str,
    display_name: str | None,
) -> UUID:
    """Crée une row `users` "shell" sans matériel crypto (is_system=TRUE).

    Pour : l'admin local (keycloak_sub=None) ou un admin Keycloak avant son
    premier bootstrap crypto. La row sera convertie en vrai user au moment
    du first-login via `convert_system_user_to_real`.
    """
    return await conn.fetchval(
        """
        INSERT INTO users (keycloak_sub, email, display_name, is_system)
        VALUES ($1, $2, $3, TRUE)
        RETURNING id
        """,
        keycloak_sub,
        email,
        display_name,
    )


async def convert_system_user_to_real(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
    rsa_public_key: bytes,
    salt_passphrase: bytes,
    salt_recovery: bytes,
    encrypted_rsa_private_key: bytes,
    encrypted_sym_key_by_pass: bytes,
    encrypted_sym_key_by_recovery: bytes,
    encrypted_rsa_private_key_by_recovery: bytes,
    kdf_memory_kb: int,
    kdf_iterations: int,
    kdf_parallelism: int,
    rsa_key_size: int,
) -> None:
    """UPDATE qui flippe is_system=FALSE et populate les colonnes crypto.

    Utilisé au first-login lorsqu'un admin Keycloak avait déjà une row shell
    créée par `require_admin_jwt` lors d'un accès admin antérieur. Idempotent
    si appelé sur un user déjà real (pas de side-effect dévastateur, mais
    écrase les blobs — ne pas appeler dans ce cas, c'est un upgrade one-shot).
    """
    await conn.execute(
        """
        UPDATE users SET
            is_system = FALSE,
            rsa_public_key = $2,
            salt_passphrase = $3,
            salt_recovery = $4,
            encrypted_rsa_private_key = $5,
            encrypted_sym_key_by_pass = $6,
            encrypted_sym_key_by_recovery = $7,
            encrypted_rsa_private_key_by_recovery = $8,
            kdf_memory_kb = $9,
            kdf_iterations = $10,
            kdf_parallelism = $11,
            rsa_key_size = $12
        WHERE id = $1
        """,
        user_id,
        rsa_public_key,
        salt_passphrase,
        salt_recovery,
        encrypted_rsa_private_key,
        encrypted_sym_key_by_pass,
        encrypted_sym_key_by_recovery,
        encrypted_rsa_private_key_by_recovery,
        kdf_memory_kb,
        kdf_iterations,
        kdf_parallelism,
        rsa_key_size,
    )
