"""Repository pour user_external_identities (LOT_02 governance).

Multi-provider OIDC : un user peut etre lie a plusieurs identites externes
(Google, GitHub, Microsoft, Apple, Keycloak interne). Une seule peut etre
primary a la fois (contrainte UNIQUE INDEX partielle).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg

from app.models.db.identity import ExternalIdentityRow


async def get_by_provider_subject(
    conn: asyncpg.Connection, provider: str, external_subject: str
) -> ExternalIdentityRow | None:
    row = await conn.fetchrow(
        "SELECT * FROM user_external_identities "
        "WHERE provider = $1 AND external_subject = $2",
        provider,
        external_subject,
    )
    return ExternalIdentityRow(**dict(row)) if row else None


async def list_by_user(
    conn: asyncpg.Connection, user_id: UUID
) -> list[ExternalIdentityRow]:
    rows = await conn.fetch(
        "SELECT * FROM user_external_identities WHERE user_id = $1 "
        "ORDER BY is_primary DESC, linked_at ASC",
        user_id,
    )
    return [ExternalIdentityRow(**dict(r)) for r in rows]


async def get_primary(
    conn: asyncpg.Connection, user_id: UUID
) -> ExternalIdentityRow | None:
    row = await conn.fetchrow(
        "SELECT * FROM user_external_identities "
        "WHERE user_id = $1 AND is_primary = TRUE",
        user_id,
    )
    return ExternalIdentityRow(**dict(row)) if row else None


async def insert(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    provider: str,
    external_subject: str,
    is_primary: bool,
    linked_email: str | None,
    linked_display_name: str | None,
) -> UUID:
    """Insere une nouvelle identite. Leve UniqueViolationError si (provider, sub)
    existe deja, ou si on tente de creer une 2e primary."""
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO user_external_identities (
            user_id, provider, external_subject, is_primary,
            linked_email, linked_display_name
        ) VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        user_id,
        provider,
        external_subject,
        is_primary,
        linked_email,
        linked_display_name,
    )
    return new_id


async def set_primary(
    conn: asyncpg.Connection, identity_id: UUID, user_id: UUID
) -> None:
    """Designe l'identite comme primary, demote l'ancienne. A faire en transaction."""
    await conn.execute(
        "UPDATE user_external_identities SET is_primary = FALSE WHERE user_id = $1",
        user_id,
    )
    await conn.execute(
        "UPDATE user_external_identities SET is_primary = TRUE "
        "WHERE id = $1 AND user_id = $2",
        identity_id,
        user_id,
    )


async def touch_last_login(conn: asyncpg.Connection, identity_id: UUID) -> None:
    await conn.execute(
        "UPDATE user_external_identities SET last_login_at = NOW() WHERE id = $1",
        identity_id,
    )


async def delete(
    conn: asyncpg.Connection, identity_id: UUID, user_id: UUID
) -> bool:
    """Supprime une identite. Retourne False si elle n'existe pas ou n'appartient
    pas au user. La logique 'pas la derniere' est dans le service."""
    result = await conn.execute(
        "DELETE FROM user_external_identities WHERE id = $1 AND user_id = $2",
        identity_id,
        user_id,
    )
    return str(result) != "DELETE 0"


async def update_snapshot(
    conn: asyncpg.Connection,
    identity_id: UUID,
    *,
    linked_email: str | None,
    linked_display_name: str | None,
    last_login_at: datetime | None = None,
) -> None:
    """Mise a jour du snapshot apres un login (pour suivre les changements)."""
    await conn.execute(
        """
        UPDATE user_external_identities
        SET linked_email = $2,
            linked_display_name = $3,
            last_login_at = COALESCE($4, last_login_at, NOW())
        WHERE id = $1
        """,
        identity_id,
        linked_email,
        linked_display_name,
        last_login_at,
    )
