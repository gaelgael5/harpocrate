"""Bootstrap d'une row `users` (is_system=TRUE) pour l'admin local.

Appelé au lifespan startup quand `HARPOCRATE_ADMIN_LOCAL_ENABLED=True`.
Permet à l'admin local d'être référencé comme `actor_user_id` dans les
inserts d'`audit_log` (CHECK `audit_log_one_actor`), au même titre qu'un
admin Keycloak post-bootstrap.

À la création, la row est `is_system=TRUE` (pas de matériel crypto, satisfait
le CHECK `users_real_user_has_crypto`). Quand l'admin local fait son premier
bootstrap (saisie de passphrase via UI), `auth_svc.bootstrap_user` détecte
la row shell pré-existante via `keycloak_sub=LOCAL_ADMIN_KEYCLOAK_SUB` et
la convertit en vrai user (`convert_system_user_to_real`).

⚠ `LOCAL_ADMIN_KEYCLOAK_SUB` DOIT matcher le `sub` du JWT généré dans
`app/api/v1/auth_local.py::_build_local_jwt`. Sinon `get_by_keycloak_sub`
ne trouvera pas la row au login → 404 first_login + 409 sur le bootstrap
qui tape la contrainte unique sur l'email.
"""
from __future__ import annotations

import asyncpg

from app.core.config import settings


# Synced avec auth_local._build_local_jwt's payload["sub"].
LOCAL_ADMIN_KEYCLOAK_SUB = "local-admin"
from app.core.logging import logger
from app.db.repositories import users as users_repo


class LocalAdminEmailConflictError(RuntimeError):
    """L'email de l'admin local est déjà utilisé par un user crypto réel."""


async def ensure_local_admin_user(pool: asyncpg.Pool) -> None:
    """Crée la row local-admin si absente, vérifie sa cohérence sinon.

    Idempotent. Lève `LocalAdminEmailConflictError` si l'email est déjà pris par
    un user `is_system=FALSE` — l'admin doit alors changer
    `HARPOCRATE_ADMIN_LOCAL_EMAIL` pour éviter d'écraser un vrai compte.
    """
    email = settings.admin_local_email
    display_name = settings.admin_local_display_name

    async with pool.acquire() as conn:
        existing = await users_repo.get_id_and_is_system_by_email(conn, email)
        if existing is not None:
            user_id, is_system = existing
            if not is_system:
                raise LocalAdminEmailConflictError(
                    f"local-admin email {email!r} is already used by a real "
                    "user (is_system=False). Change HARPOCRATE_ADMIN_LOCAL_EMAIL "
                    "to avoid colliding with a Keycloak account."
                )
            # Migration douce : les rows créées avant l'unification du sub
            # local-admin (versions antérieures) avaient keycloak_sub=NULL.
            # On patche la row pour qu'elle matche le sub du JWT — sinon
            # `get_by_keycloak_sub("local-admin")` au login retournerait
            # NULL et bloquerait le bootstrap (404 first_login + 409 conflict
            # sur unique email).
            await conn.execute(
                """
                UPDATE users
                SET keycloak_sub = $1
                WHERE id = $2 AND keycloak_sub IS NULL
                """,
                LOCAL_ADMIN_KEYCLOAK_SUB,
                user_id,
            )
            logger.info(
                "local_admin_user_exists",
                user_id=str(user_id),
                email=email,
            )
            return

        user_id = await users_repo.insert_system_user(
            conn,
            keycloak_sub=LOCAL_ADMIN_KEYCLOAK_SUB,
            email=email,
            display_name=display_name,
        )
        logger.info(
            "local_admin_user_bootstrapped",
            user_id=str(user_id),
            email=email,
        )
