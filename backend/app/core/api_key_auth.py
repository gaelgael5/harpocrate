"""Dependency FastAPI pour l'authentification par API key hrpv_* — LOT_08.

Validation order (critique — ne pas réordonner) :
1. Parse token format → 401 invalid_format (0 DB)
2. exp > now()        → 401 expired (0 DB ; skip si exp=0)
3. HMAC constant-time → 401 invalid_signature (0 DB)
4. perm ⊆ token.perms → 403 insufficient_permissions (0 DB)
5. Lookup DB (revoked_at IS NULL) + Argon2id verify → 401 (1 DB, avec cache 60s)
6. Owner still has grant on wallet → 401 owner_grant_revoked (1 DB)
7. UPDATE last_used_at (best-effort, fire-and-forget)

SECURITY : hmac.compare_digest utilisé partout, jamais '=='.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Header, HTTPException, status

from app.core import api_key_cache as cache_mod
from app.core.api_key_token import TokenParseError, is_expired, parse_token, verify_hmac
from app.core.config import settings
from app.db.pool import get_pool
from app.services.permissions import has, is_subset


@dataclass(frozen=True)
class ApiKeyCaller:
    """Représente un appelant authentifié par API key."""

    api_key_id: UUID
    owner_user_id: UUID
    wallet_id: UUID
    permissions: int
    decryption_key_b64: str  # inclus dans le token, jamais stocké en DB


# ─── Argon2id verifier (singleton léger) ──────────────────────────────────────

_ph = PasswordHasher()


def _argon2_verify(auth_hash_bytes: bytes, auth_secret_b64: str) -> bool:
    """Vérifie l'auth_secret contre le hash Argon2id stocké en DB.

    Retourne True si valide, False sinon. Ne lève pas d'exception.
    Le PasswordHasher.verify() attend le hash encodé en PHC string format.
    """
    try:
        hash_str = auth_hash_bytes.decode("utf-8")
        _ph.verify(hash_str, auth_secret_b64.encode())
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ─── last_used_at fire-and-forget ─────────────────────────────────────────────


async def _update_last_used(api_key_id: UUID, pool: asyncpg.Pool[asyncpg.Record]) -> None:
    """Met à jour last_used_at de manière best-effort (fire-and-forget)."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
                api_key_id,
            )
    except Exception:
        pass  # best-effort : on ne bloque pas la requête sur cet UPDATE


# ─── Core validation ──────────────────────────────────────────────────────────


async def validate_api_key_token(
    token: str,
    *,
    pool: asyncpg.Pool[asyncpg.Record],
    required_permission: int | None = None,
) -> ApiKeyCaller:
    """Valide un token hrpv_* selon l'ordre critique de checks.

    Lève HTTPException avec les codes d'erreur appropriés.
    required_permission : bit de permission requis par la route (None = aucun check de perm).
    """
    # ── 1. Parse format (0 DB) ────────────────────────────────────────────────
    try:
        parsed = parse_token(token)
    except TokenParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": exc.error_code, "message": "Malformed API key token"},
        ) from exc

    # ── 2. Expiration (0 DB) ──────────────────────────────────────────────────
    if is_expired(parsed.exp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "expired", "message": "API key token has expired"},
        )

    # ── 3. HMAC constant-time (0 DB) ─────────────────────────────────────────
    if not verify_hmac(
        settings.hmac_key,
        version=parsed.version,
        id_b32=parsed.api_key_id_b32,
        exp_b36=parsed.exp_b36,
        perms_hex=parsed.perms_hex,
        auth_secret_b64=parsed.auth_secret_b64,
        given_hmac_b64=parsed.hmac_b64,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_signature", "message": "Token signature is invalid"},
        )

    # ── 4. Permission check (0 DB) ────────────────────────────────────────────
    if required_permission is not None and not has(parsed.perms, required_permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "insufficient_permissions",
                "message": (
                    f"API key does not have required permission bit: {required_permission:#04x}"
                ),
            },
        )

    # ── 5. DB lookup + Argon2id (avec cache) ─────────────────────────────────
    cached = cache_mod.cache_get_valid(parsed.api_key_id, parsed.auth_secret_b64)

    if cached is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": "API key invalid or revoked"},
        )

    if cached is None:
        # Cache miss → DB lookup
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, wallet_id, owner_user_id, auth_hash, auth_salt,
                       auth_kdf_memory_kb, auth_kdf_iterations, auth_kdf_parallelism,
                       permissions, expires_at, revoked_at
                FROM api_keys
                WHERE id = $1 AND revoked_at IS NULL
                """,
                parsed.api_key_id,
            )

        if row is None:
            cache_mod.cache_set_valid(parsed.api_key_id, parsed.auth_secret_b64, valid=False)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "api_key_revoked_or_unknown",
                    "message": "API key not found or revoked",
                },
            )

        # Argon2id verify
        auth_hash_bytes = bytes(row["auth_hash"])
        if not _argon2_verify(auth_hash_bytes, parsed.auth_secret_b64):
            cache_mod.cache_set_valid(parsed.api_key_id, parsed.auth_secret_b64, valid=False)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_secret", "message": "API key authentication failed"},
            )

        cache_mod.cache_set_valid(parsed.api_key_id, parsed.auth_secret_b64, valid=True)
        wallet_id: UUID = row["wallet_id"]
        owner_user_id: UUID = row["owner_user_id"]
    else:
        # Cache hit → on doit quand même récupérer wallet_id/owner_user_id
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT wallet_id, owner_user_id FROM api_keys WHERE id = $1",
                parsed.api_key_id,
            )
        if row is None:  # pragma: no cover — race condition très improbable
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "api_key_not_found", "message": "API key not found"},
            )
        wallet_id = row["wallet_id"]
        owner_user_id = row["owner_user_id"]

    # ── 6. Owner grant check (cascade Option 2) ───────────────────────────────
    async with pool.acquire() as conn:
        grant = await conn.fetchrow(
            """
            SELECT permissions FROM wallet_grants
            WHERE wallet_id = $1 AND grantee_user_id = $2
            """,
            wallet_id,
            owner_user_id,
        )

    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "owner_grant_revoked",
                "message": "API key owner no longer has access to this wallet",
            },
        )

    # Vérif supplémentaire : les perms de la clé ne peuvent pas excéder celles de l'owner
    if not is_subset(parsed.perms, grant["permissions"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "owner_permissions_reduced",
                "message": "API key permissions exceed current owner grant permissions",
            },
        )

    # ── 7. last_used_at (fire-and-forget) ─────────────────────────────────────
    asyncio.ensure_future(  # noqa: RUF006 — intentionnellement fire-and-forget
        _update_last_used(parsed.api_key_id, pool)
    )

    return ApiKeyCaller(
        api_key_id=parsed.api_key_id,
        owner_user_id=owner_user_id,
        wallet_id=wallet_id,
        permissions=parsed.perms,
        decryption_key_b64=parsed.dkey_b64,
    )


# ─── FastAPI dependency ───────────────────────────────────────────────────────


async def require_api_key(
    authorization: Annotated[str | None, Header()] = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> ApiKeyCaller:
    """Dependency FastAPI — valide un token hrpv_* (aucune permission spécifique requise)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_bearer_token",
                "message": "Authorization header with Bearer token required",
            },
        )
    token = authorization[7:]
    if not token.startswith("hrpv_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "expected_api_key_token", "message": "Expected hrpv_* token"},
        )
    return await validate_api_key_token(token, pool=pool)


# ─── Mixed dependency (JWT ou API key) ────────────────────────────────────────


@dataclass(frozen=True)
class AuthContext:
    """Résultat de l'authentification mixte JWT/API key (retourné par require_any_auth_with_permission)."""

    user_db_id: UUID | None
    api_key: ApiKeyCaller | None
    my_permissions: int

    @property
    def is_api_key(self) -> bool:
        return self.api_key is not None

    @property
    def caller_user_id(self) -> UUID:
        """User DB ID : depuis le JWT ou depuis l'owner de l'API key."""
        if self.user_db_id is not None:
            return self.user_db_id
        assert self.api_key is not None
        return self.api_key.owner_user_id


def require_any_auth_with_permission(required_permission: int):  # type: ignore[no-untyped-def]
    """Retourne une dependency FastAPI acceptant JWT ou API key.

    Si JWT → vérifie le grant sur le wallet.
    Si API key → vérifie que wallet_id correspond et que la permission est dans le bitmap.

    Usage dans une route :
        auth: Annotated[AuthContext, Depends(require_any_auth_with_permission(PERM_READ))]
    """
    from app.core.security import CurrentUser, _validate_jwt
    from app.db.repositories import users as users_repo
    from app.db.repositories import wallets as wallets_repo
    from app.services.permissions import has

    async def _check(
        wallet_id: UUID,
        authorization: Annotated[str | None, Header()] = None,
        pool: asyncpg.Pool = Depends(get_pool),
    ) -> AuthContext:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "missing_bearer_token",
                    "message": "Authorization header required",
                },
            )

        token = authorization[7:]

        if token.startswith("hrpv_"):
            # ── API key path ──────────────────────────────────────────────────
            api_key_caller = await validate_api_key_token(
                token,
                pool=pool,
                required_permission=required_permission,
            )
            # Scope check : l'API key ne peut accéder qu'à son propre wallet
            if api_key_caller.wallet_id != wallet_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "not_found", "message": "Wallet not found"},
                )
            return AuthContext(
                user_db_id=None,
                api_key=api_key_caller,
                my_permissions=api_key_caller.permissions,
            )
        else:
            # ── JWT path ──────────────────────────────────────────────────────
            payload = await _validate_jwt(token)
            user = CurrentUser(
                keycloak_sub=payload["sub"],
                email=payload.get("email", ""),
                display_name=payload.get("name"),
            )

            async with pool.acquire() as conn:
                user_row = await users_repo.get_by_keycloak_sub(conn, user.keycloak_sub)
                if user_row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"error": "first_login", "message": "User must bootstrap first"},
                    )

                wallet = await wallets_repo.get_wallet_for_user(
                    conn, wallet_id=wallet_id, user_id=user_row.id
                )

            if wallet is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "wallet_not_found", "message": "Wallet not found"},
                )

            if not has(wallet.my_permissions, required_permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "insufficient_permissions",
                        "message": f"Missing required permission bit: {required_permission:#04x}",
                    },
                )

            return AuthContext(
                user_db_id=user_row.id,
                api_key=None,
                my_permissions=wallet.my_permissions,
            )

    return _check


def require_any_auth_with_any_of_permissions(required_any: int):  # type: ignore[no-untyped-def]
    """Comme require_any_auth_with_permission mais accepte si l'utilisateur a AU MOINS UN des bits.

    Usage :
        DescriptorAuth = Annotated[AuthContext, Depends(
            require_any_auth_with_any_of_permissions(PERM_READ | PERM_INIT)
        )]
    """
    from app.core.security import CurrentUser, _validate_jwt
    from app.db.repositories import users as users_repo
    from app.db.repositories import wallets as wallets_repo

    async def _check(
        wallet_id: UUID,
        authorization: Annotated[str | None, Header()] = None,
        pool: asyncpg.Pool = Depends(get_pool),
    ) -> AuthContext:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "missing_bearer_token",
                    "message": "Authorization header required",
                },
            )

        token = authorization[7:]

        if token.startswith("hrpv_"):
            api_key_caller = await validate_api_key_token(token, pool=pool)
            if api_key_caller.wallet_id != wallet_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "not_found", "message": "Wallet not found"},
                )
            if not (api_key_caller.permissions & required_any):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "insufficient_permissions",
                        "message": f"API key needs at least one of permission bits: {required_any:#04x}",
                    },
                )
            return AuthContext(
                user_db_id=None,
                api_key=api_key_caller,
                my_permissions=api_key_caller.permissions,
            )
        else:
            payload = await _validate_jwt(token)
            user = CurrentUser(
                keycloak_sub=payload["sub"],
                email=payload.get("email", ""),
                display_name=payload.get("name"),
            )

            async with pool.acquire() as conn:
                user_row = await users_repo.get_by_keycloak_sub(conn, user.keycloak_sub)
                if user_row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"error": "first_login", "message": "User must bootstrap first"},
                    )

                wallet = await wallets_repo.get_wallet_for_user(
                    conn, wallet_id=wallet_id, user_id=user_row.id
                )

            if wallet is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "wallet_not_found", "message": "Wallet not found"},
                )

            if not (wallet.my_permissions & required_any):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "insufficient_permissions",
                        "message": f"Missing required permission bits (any of): {required_any:#04x}",
                    },
                )

            return AuthContext(
                user_db_id=user_row.id,
                api_key=None,
                my_permissions=wallet.my_permissions,
            )

    return _check
