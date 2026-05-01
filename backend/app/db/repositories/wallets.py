"""Requêtes SQL pour les tables wallets, wallet_grants, wallet_tags."""
from __future__ import annotations

import base64
import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.db.wallet import WalletWithGrant

# ─── Helpers curseur ──────────────────────────────────────────────────────────


def encode_cursor(updated_at: datetime.datetime, wallet_id: UUID) -> str:
    """Encode (updated_at, id) en base64 URL-safe sans padding."""
    raw = f"{updated_at.isoformat()}|{wallet_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime.datetime, UUID]:
    """Décode un cursor en (updated_at, id)."""
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.datetime.fromisoformat(ts_str), UUID(id_str)


# ─── Mapping de ligne ─────────────────────────────────────────────────────────


def _row_to_wallet_with_grant(row: Any, tags: list[str]) -> WalletWithGrant:
    return WalletWithGrant(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        owner_user_id=row["owner_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        my_permissions=row["my_permissions"],
        tags=tags,
        valued_secrets_count=row["valued_secrets_count"] or 0,
        placeholder_secrets_count=row["placeholder_secrets_count"] or 0,
    )


# ─── INSERT wallet + grant + tags (transaction) ───────────────────────────────


async def insert_wallet_with_grant(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    name: str,
    description: str | None,
    owner_user_id: UUID,
    tags: list[str],
    encrypted_wallet_key: bytes,
) -> UUID:
    """Insère wallet + grant owner (permissions=63) + tags dans une transaction.

    Retourne l'UUID du wallet créé.
    """
    wallet_id: UUID = await conn.fetchval(
        """
        INSERT INTO wallets (name, description, owner_user_id)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        name,
        description,
        owner_user_id,
    )

    await conn.execute(
        """
        INSERT INTO wallet_grants (wallet_id, grantee_user_id, encrypted_wallet_key,
                                   permissions, granted_by_user_id)
        VALUES ($1, $2, $3, 63, $4)
        """,
        wallet_id,
        owner_user_id,
        encrypted_wallet_key,
        owner_user_id,
    )

    if tags:
        await conn.executemany(
            "INSERT INTO wallet_tags (wallet_id, tag) VALUES ($1, $2)",
            [(wallet_id, tag) for tag in tags],
        )

    return wallet_id


# ─── SELECT liste paginée ─────────────────────────────────────────────────────


async def list_wallets_for_user(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID,
    limit: int,
    cursor_updated_at: datetime.datetime | None,
    cursor_id: UUID | None,
    tag_filter: str | None,
    name_contains: str | None,
) -> list[WalletWithGrant]:
    """Retourne les wallets accessibles par user_id, avec pagination cursor-based."""
    rows = await conn.fetch(
        """
        SELECT
            w.id, w.name, w.description, w.owner_user_id, w.created_at, w.updated_at,
            wg.permissions AS my_permissions,
            COALESCE(s.valued, 0)       AS valued_secrets_count,
            COALESCE(s.placeholder, 0)  AS placeholder_secrets_count
        FROM wallets w
        JOIN wallet_grants wg ON wg.wallet_id = w.id AND wg.grantee_user_id = $1
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE is_placeholder = FALSE) AS valued,
                COUNT(*) FILTER (WHERE is_placeholder = TRUE)  AS placeholder
            FROM secrets WHERE wallet_id = w.id
        ) s ON true
        WHERE
            ($2::timestamptz IS NULL
             OR (w.updated_at, w.id) < ($2::timestamptz, $3::uuid))
            AND ($4::text IS NULL OR EXISTS (
                SELECT 1 FROM wallet_tags wt
                WHERE wt.wallet_id = w.id AND wt.tag = $4
            ))
            AND ($5::text IS NULL OR w.name ILIKE '%' || $5 || '%')
        ORDER BY w.updated_at DESC, w.id DESC
        LIMIT $6
        """,
        user_id,
        cursor_updated_at,
        cursor_id,
        tag_filter,
        name_contains,
        limit,
    )

    if not rows:
        return []

    wallet_ids = [r["id"] for r in rows]
    tag_rows = await conn.fetch(
        "SELECT wallet_id, tag FROM wallet_tags WHERE wallet_id = ANY($1::uuid[])",
        wallet_ids,
    )

    tags_by_wallet: dict[UUID, list[str]] = {}
    for tr in tag_rows:
        tags_by_wallet.setdefault(tr["wallet_id"], []).append(tr["tag"])

    return [
        _row_to_wallet_with_grant(row, tags_by_wallet.get(row["id"], []))
        for row in rows
    ]


# ─── SELECT wallet unique ─────────────────────────────────────────────────────


async def get_wallet_for_user(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    user_id: UUID,
) -> WalletWithGrant | None:
    """Retourne le wallet si user_id a un grant, None sinon (pas de 403, cf spec)."""
    row = await conn.fetchrow(
        """
        SELECT
            w.id, w.name, w.description, w.owner_user_id, w.created_at, w.updated_at,
            wg.permissions AS my_permissions,
            COALESCE(s.valued, 0)       AS valued_secrets_count,
            COALESCE(s.placeholder, 0)  AS placeholder_secrets_count
        FROM wallets w
        JOIN wallet_grants wg ON wg.wallet_id = w.id AND wg.grantee_user_id = $2
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE is_placeholder = FALSE) AS valued,
                COUNT(*) FILTER (WHERE is_placeholder = TRUE)  AS placeholder
            FROM secrets WHERE wallet_id = w.id
        ) s ON true
        WHERE w.id = $1
        """,
        wallet_id,
        user_id,
    )

    if row is None:
        return None

    tag_rows = await conn.fetch(
        "SELECT tag FROM wallet_tags WHERE wallet_id = $1",
        wallet_id,
    )
    tags = [tr["tag"] for tr in tag_rows]

    return _row_to_wallet_with_grant(row, tags)


# ─── UPDATE wallet (PATCH) ────────────────────────────────────────────────────


async def update_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    name: str | None,
    description: str | None,
    tags: list[str] | None,
) -> None:
    """Met à jour name/description si fournis. Remplace les tags si fournis."""
    parts: list[str] = []
    params: list[Any] = []
    idx = 1

    if name is not None:
        parts.append(f"name = ${idx}")
        params.append(name)
        idx += 1

    if description is not None:
        parts.append(f"description = ${idx}")
        params.append(description)
        idx += 1

    if parts:
        params.append(wallet_id)
        await conn.execute(
            f"UPDATE wallets SET {', '.join(parts)} WHERE id = ${idx}",
            *params,
        )

    if tags is not None:
        await conn.execute(
            "DELETE FROM wallet_tags WHERE wallet_id = $1",
            wallet_id,
        )
        if tags:
            await conn.executemany(
                "INSERT INTO wallet_tags (wallet_id, tag) VALUES ($1, $2)",
                [(wallet_id, tag) for tag in tags],
            )


# ─── DELETE wallet ────────────────────────────────────────────────────────────


async def delete_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
    wallet_id: UUID,
) -> None:
    """Hard-delete du wallet (cascade sur grants, secrets, api_keys, tags)."""
    await conn.execute("DELETE FROM wallets WHERE id = $1", wallet_id)


# ─── Transfer ownership ───────────────────────────────────────────────────────


async def grant_exists(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    user_id: UUID,
) -> bool:
    """Retourne True si user_id a un grant sur wallet_id."""
    val: int | None = await conn.fetchval(
        "SELECT 1 FROM wallet_grants WHERE wallet_id = $1 AND grantee_user_id = $2",
        wallet_id,
        user_id,
    )
    return val is not None


async def transfer_ownership(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    new_owner_user_id: UUID,
) -> None:
    """Change owner_user_id du wallet."""
    await conn.execute(
        "UPDATE wallets SET owner_user_id = $1 WHERE id = $2",
        new_owner_user_id,
        wallet_id,
    )


# ─── Lookup utilisateur par email ─────────────────────────────────────────────


async def get_user_by_email(
    conn: asyncpg.Connection[asyncpg.Record],
    email: str,
) -> dict[str, Any] | None:
    """Retourne id, email, display_name, rsa_public_key pour l'email donné."""
    row = await conn.fetchrow(
        "SELECT id, email, display_name, rsa_public_key FROM users WHERE email = $1",
        email,
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "rsa_public_key": bytes(row["rsa_public_key"]),
    }
