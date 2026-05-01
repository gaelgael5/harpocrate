"""Requêtes SQL pour la table secrets + secret_tags — LOT_05."""
from __future__ import annotations

import base64
import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.secret import SecretRow

# ─── Helpers curseur ──────────────────────────────────────────────────────────


def encode_cursor(updated_at: datetime.datetime, secret_id: UUID) -> str:
    """Encode (updated_at, id) en base64 URL-safe sans padding."""
    raw = f"{updated_at.isoformat()}|{secret_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime.datetime, UUID]:
    """Décode un cursor en (updated_at, id). ValueError si malformé."""
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.datetime.fromisoformat(ts_str), UUID(id_str)


# ─── Mapping de ligne ─────────────────────────────────────────────────────────


def _row_to_secret(row: Any, tags: list[str]) -> SecretRow:
    return SecretRow(
        id=row["id"],
        wallet_id=row["wallet_id"],
        name=row["name"],
        description=row["description"],
        encrypted_value=(
            bytes(row["encrypted_value"]) if row["encrypted_value"] is not None else None
        ),
        is_placeholder=row["is_placeholder"],
        generation_version=row["generation_version"],
        linked_secret_id=row["linked_secret_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by_user_id=row["created_by_user_id"],
        created_by_api_key_id=row["created_by_api_key_id"],
        updated_by_user_id=row["updated_by_user_id"],
        updated_by_api_key_id=row["updated_by_api_key_id"],
        tags=tags,
    )


# ─── SELECT liste paginée ─────────────────────────────────────────────────────


async def list_secrets(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    limit: int,
    cursor_updated_at: datetime.datetime | None,
    cursor_id: UUID | None,
    tag_filter: str | None,
    name_contains: str | None,
) -> list[SecretRow]:
    """Retourne les secrets d'un wallet, paginés (updated_at DESC, id DESC)."""
    rows = await conn.fetch(
        """
        SELECT
            s.id, s.wallet_id, s.name, s.description,
            s.encrypted_value, s.is_placeholder,
            s.generation_version, s.linked_secret_id,
            s.created_at, s.updated_at,
            s.created_by_user_id, s.created_by_api_key_id,
            s.updated_by_user_id, s.updated_by_api_key_id
        FROM secrets s
        WHERE
            s.wallet_id = $1
            AND ($2::timestamptz IS NULL
                 OR (s.updated_at, s.id) < ($2::timestamptz, $3::uuid))
            AND ($4::text IS NULL OR EXISTS (
                SELECT 1 FROM secret_tags st
                WHERE st.secret_id = s.id AND st.tag = $4
            ))
            AND ($5::text IS NULL OR s.name ILIKE '%' || $5 || '%')
        ORDER BY s.updated_at DESC, s.id DESC
        LIMIT $6
        """,
        wallet_id,
        cursor_updated_at,
        cursor_id,
        tag_filter,
        name_contains,
        limit,
    )

    if not rows:
        return []

    secret_ids = [r["id"] for r in rows]
    tag_rows = await conn.fetch(
        "SELECT secret_id, tag FROM secret_tags WHERE secret_id = ANY($1::uuid[])",
        secret_ids,
    )

    tags_by_secret: dict[UUID, list[str]] = {}
    for tr in tag_rows:
        tags_by_secret.setdefault(tr["secret_id"], []).append(tr["tag"])

    return [_row_to_secret(row, tags_by_secret.get(row["id"], [])) for row in rows]


# ─── SELECT secret unique par nom ─────────────────────────────────────────────


async def get_secret_by_name(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
) -> SecretRow | None:
    """Retourne le secret (avec tags) si trouvé, None sinon."""
    row = await conn.fetchrow(
        """
        SELECT
            id, wallet_id, name, description,
            encrypted_value, is_placeholder,
            generation_version, linked_secret_id,
            created_at, updated_at,
            created_by_user_id, created_by_api_key_id,
            updated_by_user_id, updated_by_api_key_id
        FROM secrets
        WHERE wallet_id = $1 AND name = $2
        """,
        wallet_id,
        name,
    )
    if row is None:
        return None

    tag_rows = await conn.fetch(
        "SELECT tag FROM secret_tags WHERE secret_id = $1",
        row["id"],
    )
    tags = [tr["tag"] for tr in tag_rows]
    return _row_to_secret(row, tags)


# ─── SELECT encrypted_wallet_key du caller ────────────────────────────────────


async def get_caller_encrypted_wallet_key(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    user_id: UUID,
) -> bytes | None:
    """Retourne encrypted_wallet_key depuis wallet_grants pour le caller donné."""
    val: bytes | None = await conn.fetchval(
        "SELECT encrypted_wallet_key FROM wallet_grants "
        "WHERE wallet_id = $1 AND grantee_user_id = $2",
        wallet_id,
        user_id,
    )
    if val is None:
        return None
    return bytes(val)


# ─── INSERT secret + tags ─────────────────────────────────────────────────────


async def insert_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    description: str | None,
    encrypted_value: bytes,
    tags: list[str],
    created_by_user_id: UUID,
) -> UUID:
    """Insère un secret non-placeholder. Lève UniqueViolationError si (wallet, name) existe."""
    secret_id: UUID = await conn.fetchval(
        """
        INSERT INTO secrets (
            wallet_id, name, description, encrypted_value,
            is_placeholder, created_by_user_id
        )
        VALUES ($1, $2, $3, $4, FALSE, $5)
        RETURNING id
        """,
        wallet_id,
        name,
        description,
        encrypted_value,
        created_by_user_id,
    )

    if tags:
        await conn.executemany(
            "INSERT INTO secret_tags (secret_id, tag) VALUES ($1, $2)",
            [(secret_id, tag) for tag in tags],
        )

    return secret_id


# ─── UPDATE secret — valeur (PUT) ─────────────────────────────────────────────


async def update_secret_value(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    secret_id: UUID,
    encrypted_value: bytes,
    updated_by_user_id: UUID,
) -> int:
    """Met à jour encrypted_value + incrémente generation_version.

    Retourne la nouvelle generation_version.
    """
    new_version: int = await conn.fetchval(
        """
        UPDATE secrets
        SET
            encrypted_value = $2,
            updated_by_user_id = $3,
            generation_version = generation_version + 1
        WHERE id = $1
        RETURNING generation_version
        """,
        secret_id,
        encrypted_value,
        updated_by_user_id,
    )
    return new_version


# ─── UPDATE secret — métadonnées (PATCH) ─────────────────────────────────────


async def update_secret_meta(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    secret_id: UUID,
    description: str | None,
    tags: list[str] | None,
    updated_by_user_id: UUID,
) -> None:
    """Met à jour description et/ou tags sans toucher à la valeur."""
    if description is not None:
        await conn.execute(
            """
            UPDATE secrets
            SET description = $2, updated_by_user_id = $3
            WHERE id = $1
            """,
            secret_id,
            description,
            updated_by_user_id,
        )

    if tags is not None:
        await conn.execute(
            "DELETE FROM secret_tags WHERE secret_id = $1",
            secret_id,
        )
        if tags:
            await conn.executemany(
                "INSERT INTO secret_tags (secret_id, tag) VALUES ($1, $2)",
                [(secret_id, tag) for tag in tags],
            )


# ─── DELETE secret ────────────────────────────────────────────────────────────


async def delete_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    secret_id: UUID,
) -> None:
    """Supprime le secret (cascade sur secret_tags)."""
    await conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)
