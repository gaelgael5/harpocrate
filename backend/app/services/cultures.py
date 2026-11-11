"""Cultures activables (épic « Cultures et templates Listmonk paramétrés en base », feature 1).

Une culture activée peut recevoir des contenus paramétrés (templates de mails) ; la
culture par défaut sert de repli quand celle d'un utilisateur n'est pas activée ou n'a
pas de contenu. Activer une culture n'ouvre PAS la langue à l'UI ni à
`users.preferred_locale` : c'est un sujet séparé (décision de cadrage du 2026-11-11).
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.db.repositories import cultures as repo
from app.models.db.culture import CultureRow
from app.services.audit import audit_log_insert


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "culture_not_found", "message": "Culture not found"},
    )


def _conflict(error: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"error": error, "message": message}
    )


async def list_cultures(conn: asyncpg.Connection[asyncpg.Record]) -> list[CultureRow]:
    return await repo.db_list(conn)


async def update_culture(
    conn: asyncpg.Connection[asyncpg.Record],
    code: str,
    *,
    enabled: bool | None,
    make_default: bool,
    actor_user_id: UUID,
    actor_ip: str | None,
) -> CultureRow:
    """Active / désactive une culture et/ou la désigne comme culture par défaut.

    On ne « retire » pas le défaut d'une culture : on en désigne une autre. Il y a ainsi
    toujours un repli, et le refus de désactiver la culture par défaut suffit à garder
    l'invariant « la culture par défaut est activée ».
    """
    async with conn.transaction():
        current = await repo.db_get(conn, code, for_update=True)
        if current is None:
            raise _not_found()
        will_be_enabled = current.enabled if enabled is None else enabled
        if not will_be_enabled and current.is_default:
            raise _conflict(
                "default_culture_cannot_be_disabled",
                "Designate another default culture before disabling this one",
            )
        if make_default and not will_be_enabled:
            raise _conflict("culture_disabled", "Only an enabled culture can be the default")

        row = current
        if enabled is not None and enabled != current.enabled:
            row = await _set_enabled(conn, current, enabled, actor_user_id, actor_ip)
        if make_default and not current.is_default:
            row = await _make_default(conn, current, actor_user_id, actor_ip)
    return row


async def _set_enabled(
    conn: asyncpg.Connection[asyncpg.Record],
    current: CultureRow,
    enabled: bool,
    actor_user_id: UUID,
    actor_ip: str | None,
) -> CultureRow:
    row = await repo.db_set_enabled(conn, current.code, enabled)
    if row is None:
        raise _not_found()
    await audit_log_insert(
        conn,
        "culture.enabled" if enabled else "culture.disabled",
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        metadata={"code": current.code},
    )
    return row


async def _make_default(
    conn: asyncpg.Connection[asyncpg.Record],
    current: CultureRow,
    actor_user_id: UUID,
    actor_ip: str | None,
) -> CultureRow:
    previous = next((c.code for c in await repo.db_list(conn) if c.is_default), None)
    await repo.db_clear_default(conn)
    row = await repo.db_mark_default(conn, current.code)
    if row is None:
        raise _not_found()
    await audit_log_insert(
        conn,
        "culture.default_changed",
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        metadata={"code": current.code, "previous_default": previous},
    )
    return row
