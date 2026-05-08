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

_LOCAL_ADMIN_SUB = "local-admin"


async def resolve_admin_user_id(
    *,
    keycloak_sub: str,
    email: str,
    display_name: str | None,
) -> UUID:
    """Résout l'UUID `users.id` correspondant au JWT admin.

    - sub == 'local-admin' → cherche par email (la row a été créée au lifespan
      par `local_admin_bootstrap`). Si absente, c'est une erreur de
      configuration (admin_local_enabled=True mais bootstrap non exécuté).
    - sub Keycloak → cherche par keycloak_sub. Si absent, crée une row shell
      `is_system=TRUE` qui sera convertie en vrai user au first-login.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if keycloak_sub == _LOCAL_ADMIN_SUB:
            existing = await users_repo.get_id_and_is_system_by_email(conn, email)
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "local_admin_not_provisioned",
                        "message": (
                            "Local admin user row missing — startup bootstrap "
                            "did not run. Check HARPOCRATE_ADMIN_LOCAL_ENABLED."
                        ),
                    },
                )
            return existing[0]

        existing_id = await users_repo.get_id_by_keycloak_sub(conn, keycloak_sub)
        if existing_id is not None:
            return existing_id

        # Première fois qu'on voit cet admin Keycloak — pas encore de bootstrap
        # crypto. On crée une row shell pour qu'il puisse agir sur les
        # endpoints admin (audit/backup/...) en attendant son first-login.
        return await users_repo.insert_system_user(
            conn,
            keycloak_sub=keycloak_sub,
            email=email,
            display_name=display_name,
        )
