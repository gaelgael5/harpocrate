"""Templates Listmonk par type de mail et par culture (épic « Cultures et templates
Listmonk paramétrés en base », feature 2).

La connexion (URL, utilisateur, token) est gérée par `listmonk_connection`.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import cultures as cultures_repo
from app.db.repositories import listmonk_templates as repo
from app.db.repositories import system_metadata as metadata_repo
from app.db.repositories import users as users_repo
from app.models.db.listmonk_template import ListmonkTemplateRow, ResolvedTemplate
from app.services.audit import audit_log_insert

# Types de mail paramétrables — miroir du CHECK de la migration 035.
PURPOSES: tuple[str, ...] = ("recovery",)
PURPOSE_RECOVERY = "recovery"

_LEGACY_IMPORT_MARKER = "listmonk_legacy_templates_imported"


async def list_templates(conn: asyncpg.Connection[asyncpg.Record]) -> list[ListmonkTemplateRow]:
    return await repo.db_list(conn)


async def set_template(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    purpose: str,
    culture_code: str,
    template_id: int,
    actor_user_id: UUID,
    actor_ip: str | None,
) -> ListmonkTemplateRow:
    async with conn.transaction():
        culture = await cultures_repo.db_get(conn, culture_code, for_update=True)
        if culture is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "culture_not_found", "message": "Culture not found"},
            )
        # Un template sur une culture désactivée ne serait jamais choisi à l'envoi
        # (`db_resolve` ignore les cultures désactivées) : on refuse plutôt que de
        # laisser croire qu'il est actif.
        if not culture.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "culture_disabled", "message": "Enable the culture first"},
            )
        previous = await repo.db_get_for_update(conn, purpose, culture_code)
        if previous is not None and previous.template_id == template_id:
            return previous
        row = await repo.db_upsert(
            conn,
            purpose=purpose,
            culture_code=culture_code,
            template_id=template_id,
            updated_by_user_id=actor_user_id,
        )
        await audit_log_insert(
            conn,
            "listmonk_template.set",
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            metadata={
                "purpose": purpose,
                "culture_code": culture_code,
                "template_id": template_id,
                "previous_template_id": previous.template_id if previous else None,
            },
        )
    return row


async def delete_template(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    purpose: str,
    culture_code: str,
    actor_user_id: UUID,
    actor_ip: str | None,
) -> None:
    async with conn.transaction():
        previous = await repo.db_get_for_update(conn, purpose, culture_code)
        if previous is None or not await repo.db_delete(conn, purpose, culture_code):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "template_not_found", "message": "No template for this culture"},
            )
        await audit_log_insert(
            conn,
            "listmonk_template.deleted",
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            metadata={
                "purpose": purpose,
                "culture_code": culture_code,
                "previous_template_id": previous.template_id,
            },
        )


async def resolve_template_for_user(
    conn: asyncpg.Connection[asyncpg.Record], purpose: str, user_id: UUID
) -> ResolvedTemplate | None:
    """Template à envoyer à `user_id` : celui de sa culture (`users.preferred_locale`)
    si elle est activée et pourvue, sinon celui de la culture par défaut, sinon None."""
    locale = await users_repo.get_preferred_locale(conn, user_id)
    return await repo.db_resolve(conn, purpose, locale)


async def import_legacy_env_templates(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """Reprise UNIQUE des variables HARPOCRATE_LISTMONK_TEMPLATE_RECOVERY_* au boot.

    Un témoin dans system_metadata empêche de réimporter plus tard : sans lui, un admin
    qui supprime tous ses templates depuis l'UI les verrait revenir au redémarrage
    suivant tant que les variables traînent dans le .env. Les templates déjà en base ne
    sont jamais écrasés (`db_import_legacy`).

    Le témoin n'est posé que si des variables étaient fournies : une instance qui
    démarre sans elles (par exemple parce qu'elle comptait sur les anciens défauts du
    compose) peut encore les poser dans le .env et voir la reprise au boot suivant.
    """
    legacy = {
        code: template_id
        for code, template_id in (
            ("en", settings.listmonk_template_recovery_en),
            ("fr", settings.listmonk_template_recovery_fr),
        )
        if template_id is not None
    }
    if not legacy:
        return
    async with conn.transaction():
        if await metadata_repo.get_value(conn, _LEGACY_IMPORT_MARKER):
            return
        inserted = await repo.db_import_legacy(conn, PURPOSE_RECOVERY, legacy)
        await metadata_repo.set_value(conn, _LEGACY_IMPORT_MARKER, True)
    logger.info(
        "listmonk_legacy_templates_import",
        provided=sorted(legacy),
        inserted=inserted,
    )
