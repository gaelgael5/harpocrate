"""Service auth — logique métier bootstrap et mise à jour crypto."""
from __future__ import annotations

import base64
import datetime
from uuid import UUID

import asyncpg
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import (
    load_der_public_key,
    load_pem_public_key,
)
from fastapi import HTTPException, status

from app.core.config import settings
from app.db.repositories import users as users_repo
from app.models.api.auth import BootstrapRequest, PassphraseChangeRequest, RecoveryRenewRequest
from app.models.db.user import UserRow
from app.services.audit import audit_log_insert

# ─── Helpers de validation ────────────────────────────────────────────────────


async def _is_system_row(
    conn: asyncpg.Connection[asyncpg.Record],
    user_id: UUID,
) -> bool:
    """Lit uniquement le flag is_system. Sûr pour les system users (pas de
    déréférencement des colonnes crypto NULL via _row_to_user)."""
    return bool(await conn.fetchval(
        "SELECT is_system FROM users WHERE id = $1", user_id
    ))


def _decode_base64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_base64",
                "message": f"Field '{field}' is not valid base64",
                "details": {"field": field},
            },
        ) from exc


def _check_salt(value: str, field: str) -> bytes:
    raw = _decode_base64(value, field)
    if len(raw) != 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_salt_size",
                "message": f"Salt '{field}' must be exactly 16 bytes (got {len(raw)})",
                "details": {"field": field, "size": len(raw)},
            },
        )
    return raw


def _check_kdf_floors(memory_kb: int, iterations: int, parallelism: int) -> None:
    violations: list[str] = []
    if memory_kb < settings.kdf_memory_kb:
        violations.append(
            f"kdf_memory_kb={memory_kb} < floor {settings.kdf_memory_kb}"
        )
    if iterations < settings.kdf_iterations:
        violations.append(
            f"kdf_iterations={iterations} < floor {settings.kdf_iterations}"
        )
    if parallelism < settings.kdf_parallelism:
        violations.append(
            f"kdf_parallelism={parallelism} < floor {settings.kdf_parallelism}"
        )
    if violations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "kdf_floor_violation",
                "message": "KDF parameters below minimum floor",
                "details": {"violations": violations},
            },
        )


def _parse_rsa_public_key(b64_value: str) -> bytes:
    """Parse et valide la clé RSA publique (DER ou PEM). Retourne les bytes bruts."""
    raw = _decode_base64(b64_value, "rsa_public_key")
    # Tenter DER d'abord, puis PEM
    try:
        load_der_public_key(raw)
        return raw
    except (ValueError, UnsupportedAlgorithm, TypeError):
        pass
    try:
        load_pem_public_key(raw)
        return raw
    except (ValueError, UnsupportedAlgorithm, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_rsa_key",
                "message": (
                    "rsa_public_key must be a valid RSA public key (DER or PEM base64-encoded)"
                ),
            },
        ) from exc


# ─── Service operations ───────────────────────────────────────────────────────


async def bootstrap_user(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    keycloak_sub: str,
    email: str,
    display_name: str | None,
    req: BootstrapRequest,
) -> UUID:
    """Valide la requête et insère le matériel crypto de l'utilisateur."""
    # Validations
    _check_kdf_floors(req.kdf_memory_kb, req.kdf_iterations, req.kdf_parallelism)

    if req.rsa_key_size not in (2048, 4096):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_rsa_key_size",
                "message": f"rsa_key_size must be 2048 or 4096 (got {req.rsa_key_size})",
            },
        )

    rsa_pub_bytes = _parse_rsa_public_key(req.rsa_public_key)
    salt_pass = _check_salt(req.salt_passphrase, "salt_passphrase")
    salt_rec = _check_salt(req.salt_recovery, "salt_recovery")
    enc_priv = _decode_base64(req.encrypted_rsa_private_key, "encrypted_rsa_private_key")
    enc_sym_pass = _decode_base64(req.encrypted_sym_key_by_pass, "encrypted_sym_key_by_pass")
    enc_sym_rec = _decode_base64(
        req.encrypted_sym_key_by_recovery, "encrypted_sym_key_by_recovery"
    )
    enc_rsa_priv_by_recovery = _decode_base64(
        req.encrypted_rsa_private_key_by_recovery,
        "encrypted_rsa_private_key_by_recovery",
    )

    # Cas pré-existant : un admin Keycloak qui a touché /admin/* avant son
    # first-login a déjà une row shell (is_system=TRUE) créée par
    # `require_admin_jwt`. On la convertit en vrai user au lieu d'un INSERT
    # qui échouerait sur UNIQUE(keycloak_sub).
    existing_id = await users_repo.get_id_by_keycloak_sub(conn, keycloak_sub)
    if existing_id is not None:
        # Si la row a déjà du matériel crypto (is_system=FALSE), c'est un
        # vrai user déjà bootstrappé → 409 (comportement historique).
        is_shell = await _is_system_row(conn, existing_id)
        if not is_shell:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "already_bootstrapped",
                    "message": "User has already completed bootstrap",
                },
            )
        await users_repo.convert_system_user_to_real(
            conn,
            user_id=existing_id,
            rsa_public_key=rsa_pub_bytes,
            salt_passphrase=salt_pass,
            salt_recovery=salt_rec,
            encrypted_rsa_private_key=enc_priv,
            encrypted_sym_key_by_pass=enc_sym_pass,
            encrypted_sym_key_by_recovery=enc_sym_rec,
            encrypted_rsa_private_key_by_recovery=enc_rsa_priv_by_recovery,
            kdf_memory_kb=req.kdf_memory_kb,
            kdf_iterations=req.kdf_iterations,
            kdf_parallelism=req.kdf_parallelism,
            rsa_key_size=req.rsa_key_size,
        )
        # Met à jour l'email/display_name si Keycloak les a changés depuis
        # la création de la shell row.
        await users_repo.set_email(conn, user_id=existing_id, email=email)
        user_id = existing_id
    else:
        try:
            user_id = await users_repo.insert_bootstrap(
                conn,
                keycloak_sub=keycloak_sub,
                email=email,
                display_name=display_name,
                rsa_public_key=rsa_pub_bytes,
                salt_passphrase=salt_pass,
                salt_recovery=salt_rec,
                encrypted_rsa_private_key=enc_priv,
                encrypted_sym_key_by_pass=enc_sym_pass,
                encrypted_sym_key_by_recovery=enc_sym_rec,
                encrypted_rsa_private_key_by_recovery=enc_rsa_priv_by_recovery,
                kdf_memory_kb=req.kdf_memory_kb,
                kdf_iterations=req.kdf_iterations,
                kdf_parallelism=req.kdf_parallelism,
                rsa_key_size=req.rsa_key_size,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "already_bootstrapped",
                    "message": "User has already completed bootstrap",
                },
            ) from exc

    await audit_log_insert(
        conn,
        "user.bootstrapped",
        actor_user_id=user_id,
        target_user_id=user_id,
        metadata={"keycloak_sub": keycloak_sub, "email": email},
    )

    return user_id


async def change_passphrase(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user: UserRow,
    req: PassphraseChangeRequest,
) -> datetime.datetime:
    """Valide et met à jour les blobs passphrase."""
    _check_kdf_floors(req.kdf_memory_kb, req.kdf_iterations, req.kdf_parallelism)
    new_salt = _check_salt(req.new_salt_passphrase, "new_salt_passphrase")
    new_enc_priv = _decode_base64(
        req.new_encrypted_rsa_private_key, "new_encrypted_rsa_private_key"
    )
    new_enc_sym = _decode_base64(
        req.new_encrypted_sym_key_by_pass, "new_encrypted_sym_key_by_pass"
    )

    updated_at = await users_repo.update_passphrase(
        conn,
        user_id=user.id,
        new_salt_passphrase=new_salt,
        new_encrypted_rsa_private_key=new_enc_priv,
        new_encrypted_sym_key_by_pass=new_enc_sym,
        kdf_memory_kb=req.kdf_memory_kb,
        kdf_iterations=req.kdf_iterations,
        kdf_parallelism=req.kdf_parallelism,
    )

    await audit_log_insert(
        conn,
        "user.passphrase_changed",
        actor_user_id=user.id,
        target_user_id=user.id,
        metadata={"keycloak_sub": user.keycloak_sub},
    )

    return updated_at


async def renew_recovery(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user: UserRow,
    req: RecoveryRenewRequest,
) -> datetime.datetime:
    """Valide et met à jour le blob recovery.

    LOT_57 fix : on re-chiffre AUSSI rsa_priv avec la nouvelle recovery_key
    (sinon le flow recovery casserait — l'ancien blob by_recovery serait
    déchiffrable par les anciens 24 mots, mais l'user a régénéré).
    """
    new_salt = _check_salt(req.new_salt_recovery, "new_salt_recovery")
    new_enc_rec = _decode_base64(
        req.new_encrypted_sym_key_by_recovery, "new_encrypted_sym_key_by_recovery"
    )
    new_enc_rsa_priv_by_rec = _decode_base64(
        req.new_encrypted_rsa_private_key_by_recovery,
        "new_encrypted_rsa_private_key_by_recovery",
    )

    updated_at = await users_repo.update_recovery(
        conn,
        user_id=user.id,
        new_salt_recovery=new_salt,
        new_encrypted_sym_key_by_recovery=new_enc_rec,
        new_encrypted_rsa_private_key_by_recovery=new_enc_rsa_priv_by_rec,
    )

    await audit_log_insert(
        conn,
        "user.recovery_renewed",
        actor_user_id=user.id,
        target_user_id=user.id,
        metadata={"keycloak_sub": user.keycloak_sub},
    )

    return updated_at
