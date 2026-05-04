"""Requêtes SQL pour la table secrets + secret_tags — LOT_05/06/18."""
from __future__ import annotations

import base64
import datetime
import json
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
    # asyncpg décode JSONB → str en asyncpg < 0.30, dict en ≥ 0.30.
    # On normalise en dict | None ici pour isoler le comportement.
    raw_descriptor = row["generation_descriptor"]
    descriptor: dict[str, Any] | None
    if raw_descriptor is None:
        descriptor = None
    elif isinstance(raw_descriptor, dict):
        descriptor = raw_descriptor
    else:
        descriptor = json.loads(str(raw_descriptor))

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
        generation_descriptor=descriptor,
        type_uuid=row.get("type_uuid"),
        schema_version_uuid=row.get("schema_version_uuid"),
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
            s.generation_descriptor,
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
            generation_descriptor,
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
    type_uuid: UUID | None = None,
    schema_version_uuid: UUID | None = None,
) -> UUID:
    """Insère un secret non-placeholder. Lève UniqueViolationError si (wallet, name) existe."""
    secret_id: UUID = await conn.fetchval(
        """
        INSERT INTO secrets (
            wallet_id, name, description, encrypted_value,
            is_placeholder, created_by_user_id, type_uuid, schema_version_uuid
        )
        VALUES ($1, $2, $3, $4, FALSE, $5, $6, $7)
        RETURNING id
        """,
        wallet_id,
        name,
        description,
        encrypted_value,
        created_by_user_id,
        type_uuid,
        schema_version_uuid,
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


# ─── INSERT placeholder ───────────────────────────────────────────────────────


async def insert_placeholder(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str,
    description: str | None,
    generation_descriptor: dict[str, Any],
    tags: list[str],
    linked_secret_id: UUID | None,
    created_by_user_id: UUID,
) -> UUID:
    """Insère un secret placeholder (encrypted_value=NULL, is_placeholder=TRUE).

    Lève UniqueViolationError si (wallet_id, name) existe déjà.
    """
    secret_id: UUID = await conn.fetchval(
        """
        INSERT INTO secrets (
            wallet_id, name, description,
            is_placeholder, generation_descriptor,
            linked_secret_id, created_by_user_id
        )
        VALUES ($1, $2, $3, TRUE, $4::jsonb, $5, $6)
        RETURNING id
        """,
        wallet_id,
        name,
        description,
        json.dumps(generation_descriptor),
        linked_secret_id,
        created_by_user_id,
    )

    if tags:
        await conn.executemany(
            "INSERT INTO secret_tags (secret_id, tag) VALUES ($1, $2)",
            [(secret_id, tag) for tag in tags],
        )

    return secret_id


# ─── POPULATE placeholder → valued ────────────────────────────────────────────


async def populate_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    secret_id: UUID,
    encrypted_value: bytes,
    updated_by_user_id: UUID,
) -> int:
    """Peuple un placeholder : SET encrypted_value, is_placeholder=FALSE.

    Retourne la nouvelle generation_version.
    """
    new_version: int = await conn.fetchval(
        """
        UPDATE secrets
        SET
            encrypted_value = $2,
            is_placeholder = FALSE,
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


# ─── SELECT descriptor only ───────────────────────────────────────────────────


# ─── LOT_18 : path-aware queries ─────────────────────────────────────────────


async def list_by_path(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path: str,
    limit: int,
    cursor_updated_at: datetime.datetime | None,
    cursor_id: UUID | None,
) -> list[SecretRow]:
    """Liste les secrets directs d'un path (non récursif).

    path='/' → secrets sans '/' dans leur nom.
    path='/bob/' → secrets dont le nom commence par '/bob/' sans second '/'.
    """
    if path == "/":
        rows = await conn.fetch(
            """
            SELECT
                s.id, s.wallet_id, s.name, s.description,
                s.encrypted_value, s.is_placeholder,
                s.generation_version, s.linked_secret_id,
                s.generation_descriptor,
                s.created_at, s.updated_at,
                s.created_by_user_id, s.created_by_api_key_id,
                s.updated_by_user_id, s.updated_by_api_key_id
            FROM secrets s
            WHERE s.wallet_id = $1
              AND s.name NOT LIKE '%/%'
              AND ($2::timestamptz IS NULL
                   OR (s.updated_at, s.id) < ($2::timestamptz, $3::uuid))
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT $4
            """,
            wallet_id, cursor_updated_at, cursor_id, limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT
                s.id, s.wallet_id, s.name, s.description,
                s.encrypted_value, s.is_placeholder,
                s.generation_version, s.linked_secret_id,
                s.generation_descriptor,
                s.created_at, s.updated_at,
                s.created_by_user_id, s.created_by_api_key_id,
                s.updated_by_user_id, s.updated_by_api_key_id
            FROM secrets s
            WHERE s.wallet_id = $1
              AND s.name LIKE $2 || '%'
              AND s.name NOT LIKE $2 || '%/%'
              AND ($3::timestamptz IS NULL
                   OR (s.updated_at, s.id) < ($3::timestamptz, $4::uuid))
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT $5
            """,
            wallet_id, path, cursor_updated_at, cursor_id, limit,
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


async def get_tree_data(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path: str,
) -> dict[str, object]:
    """Retourne les sous-répertoires directs d'un path + count secrets à ce niveau."""
    target_depth = 1 if path == "/" else path.count("/")

    folder_rows = await conn.fetch(
        """
        SELECT DISTINCT
            pi.path_segment,
            (
                SELECT COUNT(DISTINCT pi2.secret_id)
                FROM secret_path_index pi2
                WHERE pi2.wallet_id = $1
                  AND pi2.path_segment = pi.path_segment
            ) AS secrets_count,
            (
                SELECT COUNT(DISTINCT pi3.secret_id)
                FROM secret_path_index pi3
                WHERE pi3.wallet_id = $1
                  AND pi3.depth > $3
                  AND pi3.path_segment LIKE pi.path_segment || '%'
            ) AS subfolders_count
        FROM secret_path_index pi
        WHERE pi.wallet_id = $1
          AND pi.depth = $3
          AND pi.path_segment LIKE $2 || '%'
          AND pi.path_segment != $2
        ORDER BY pi.path_segment
        """,
        wallet_id, path, target_depth,
    )

    if path == "/":
        secrets_at_level: int = await conn.fetchval(
            "SELECT COUNT(*) FROM secrets WHERE wallet_id = $1 AND name NOT LIKE '%/%'",
            wallet_id,
        )
    else:
        secrets_at_level = await conn.fetchval(
            """SELECT COUNT(*) FROM secrets
               WHERE wallet_id = $1
                 AND name LIKE $2 || '%'
                 AND name NOT LIKE $2 || '%/%'""",
            wallet_id, path,
        )

    def _folder_name(full_path: str, parent: str) -> str:
        suffix = full_path[len(parent):]
        return suffix.rstrip("/")

    return {
        "path": path,
        "secrets_at_this_level_count": secrets_at_level,
        "folders": [
            {
                "name": _folder_name(r["path_segment"], path),
                "full_path": r["path_segment"],
                "secrets_count": r["secrets_count"],
                "subfolders_count": r["subfolders_count"],
            }
            for r in folder_rows
        ],
    }


async def get_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    secret_id: UUID,
) -> SecretRow | None:
    """Retourne un secret par son UUID (avec tags). None si absent."""
    row = await conn.fetchrow(
        """
        SELECT
            id, wallet_id, name, description,
            encrypted_value, is_placeholder,
            generation_version, linked_secret_id,
            generation_descriptor,
            created_at, updated_at,
            created_by_user_id, created_by_api_key_id,
            updated_by_user_id, updated_by_api_key_id
        FROM secrets
        WHERE id = $1
        """,
        secret_id,
    )
    if row is None:
        return None

    tag_rows = await conn.fetch(
        "SELECT tag FROM secret_tags WHERE secret_id = $1",
        secret_id,
    )
    tags = [tr["tag"] for tr in tag_rows]
    return _row_to_secret(row, tags)
