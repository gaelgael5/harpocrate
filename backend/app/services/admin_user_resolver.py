"""Résolution `users.id` pour les admins JWT (Keycloak ou local).

Module séparé d'`admin_auth` pour éviter d'importer `app.core.security` au
moment du patch dans les tests (le binding `settings` y est figé à l'import,
ce qui causait des "Signature verification failed" si la fixture monkeypatch
cassait l'ordre de chargement).

`require_admin_jwt` délègue ici toute la partie DB.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.services.local_admin_bootstrap import LOCAL_ADMIN_KEYCLOAK_SUB


async def resolve_admin_user_id(
    *,
    keycloak_sub: str,
    email: str,
    display_name: str | None,
) -> UUID:
    """Résout l'UUID `users.id` correspondant au JWT admin.

    Local-admin et Keycloak sont traités de manière unifiée : lookup par
    `keycloak_sub` (qui vaut `LOCAL_ADMIN_KEYCLOAK_SUB` pour le local-admin
    depuis l'unification, cf `local_admin_bootstrap`).

    - Si la row existe → retourne son id (peu importe is_system, le
      bootstrap crypto la convertira plus tard).
    - Sinon → crée une row shell `is_system=TRUE`. Pour le local-admin
      c'est aussi un fallback (si lifespan a échoué pour x raison).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing_id = await users_repo.get_id_by_keycloak_sub(conn, keycloak_sub)
        if existing_id is not None:
            return existing_id

        # Cas particulier local-admin : si on arrive ici, c'est que le
        # lifespan bootstrap a échoué (ou que `HARPOCRATE_ADMIN_LOCAL_ENABLED`
        # vient d'être activé sans restart). On log un warning explicite
        # mais on continue (création de la row à la volée).
        is_local_admin = keycloak_sub == LOCAL_ADMIN_KEYCLOAK_SUB
        if is_local_admin:
            import structlog
            structlog.get_logger(__name__).warning(
                "local_admin_row_missing_creating_fallback",
                note="lifespan bootstrap should have created this row",
            )

        # Première fois qu'on voit cet admin (Keycloak ou local) — pas encore
        # de bootstrap crypto. On crée une row shell pour qu'il puisse agir
        # sur les endpoints admin (audit/backup/...) en attendant son
        # first-login.
        return await users_repo.insert_system_user(
            conn,
            keycloak_sub=keycloak_sub,
            email=email,
            display_name=display_name,
        )
