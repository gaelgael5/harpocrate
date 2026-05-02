"""Tests d'intégration du schéma DB (LOT_01).

Ces tests nécessitent une vraie base PostgreSQL avec la migration 001 appliquée.
Activer via : HARPOCRATE_DB_DSN_TEST=postgresql://user:pwd@host:5432/db pytest tests/test_schema.py
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import asyncpg
import pytest
import pytest_asyncio

# Toutes les fonctions de ce module sont des coroutines pytest-asyncio
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def clean_db(real_db_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    """Pool avec tables vidées entre les tests, dans le bon ordre des FK."""
    async with real_db_pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE audit_log, secret_tags, secrets, api_keys, "
            "wallet_grants, wallet_tags, wallets, users RESTART IDENTITY CASCADE"
        )
    yield real_db_pool


async def _insert_user(conn: asyncpg.Connection, sub: str, email: str) -> str:
    return cast(
        str,
        await conn.fetchval(
            """
            INSERT INTO users (
                keycloak_sub, email, rsa_public_key,
                salt_passphrase, salt_recovery,
                encrypted_rsa_private_key, encrypted_sym_key_by_pass,
                encrypted_sym_key_by_recovery,
                kdf_memory_kb, kdf_iterations, kdf_parallelism, rsa_key_size
            ) VALUES (
                $1, $2, '\\x00', '\\x00', '\\x00',
                '\\x00', '\\x00', '\\x00',
                65536, 3, 4, 2048
            )
            RETURNING id::text
            """,
            sub,
            email,
        ),
    )


async def _insert_wallet(conn: asyncpg.Connection, owner_id: str, name: str) -> str:
    return cast(
        str,
        await conn.fetchval(
            "INSERT INTO wallets (name, owner_user_id) VALUES ($1, $2::uuid) "
            "RETURNING id::text",
            name,
            owner_id,
        ),
    )


async def _insert_owner_grant(
    conn: asyncpg.Connection, wallet_id: str, owner_id: str
) -> str:
    return cast(
        str,
        await conn.fetchval(
            """
            INSERT INTO wallet_grants (
                wallet_id, grantee_user_id, encrypted_wallet_key,
                permissions, granted_by_user_id
            )
            VALUES ($1::uuid, $2::uuid, '\\x00', 63, $2::uuid)
            RETURNING id::text
            """,
            wallet_id,
            owner_id,
        ),
    )


async def test_owner_grant_protected_from_delete(clean_db: asyncpg.Pool) -> None:
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        w = await _insert_wallet(conn, u, "w")
        g = await _insert_owner_grant(conn, w, u)

        with pytest.raises(asyncpg.RaiseError, match="owner"):
            await conn.execute("DELETE FROM wallet_grants WHERE id = $1::uuid", g)


async def test_owner_grant_protected_from_permission_update(
    clean_db: asyncpg.Pool,
) -> None:
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        w = await _insert_wallet(conn, u, "w")
        g = await _insert_owner_grant(conn, w, u)

        with pytest.raises(asyncpg.RaiseError, match="owner"):
            await conn.execute(
                "UPDATE wallet_grants SET permissions = 1 WHERE id = $1::uuid",
                g,
            )


async def test_secret_placeholder_must_have_null_value(
    clean_db: asyncpg.Pool,
) -> None:
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        w = await _insert_wallet(conn, u, "w")

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO secrets (
                    wallet_id, name, encrypted_value, is_placeholder,
                    created_by_user_id
                )
                VALUES ($1::uuid, 'test', '\\x00', TRUE, $2::uuid)
                """,
                w,
                u,
            )


async def test_secret_value_required_when_not_placeholder(
    clean_db: asyncpg.Pool,
) -> None:
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        w = await _insert_wallet(conn, u, "w")

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO secrets (
                    wallet_id, name, encrypted_value, is_placeholder,
                    created_by_user_id
                )
                VALUES ($1::uuid, 'test', NULL, FALSE, $2::uuid)
                """,
                w,
                u,
            )


async def test_audit_log_requires_exactly_one_actor(clean_db: asyncpg.Pool) -> None:
    async with clean_db.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO audit_log (action) VALUES ('test.event')"
            )


async def test_permissions_bitmap_max(clean_db: asyncpg.Pool) -> None:
    """permissions doit être ≤ 63."""
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        u2 = await _insert_user(conn, "sub-2", "b@b.c")
        w = await _insert_wallet(conn, u, "w")
        await _insert_owner_grant(conn, w, u)

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO wallet_grants (
                    wallet_id, grantee_user_id, encrypted_wallet_key,
                    permissions, granted_by_user_id
                )
                VALUES ($1::uuid, $2::uuid, '\\x00', 64, $3::uuid)
                """,
                w,
                u2,
                u,
            )


async def test_permissions_must_be_nonzero(clean_db: asyncpg.Pool) -> None:
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        u2 = await _insert_user(conn, "sub-2", "b@b.c")
        w = await _insert_wallet(conn, u, "w")
        await _insert_owner_grant(conn, w, u)

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO wallet_grants (
                    wallet_id, grantee_user_id, encrypted_wallet_key,
                    permissions, granted_by_user_id
                )
                VALUES ($1::uuid, $2::uuid, '\\x00', 0, $3::uuid)
                """,
                w,
                u2,
                u,
            )


async def test_tag_normalization_enforced(clean_db: asyncpg.Pool) -> None:
    """Les tags doivent être lowercase et trimmed."""
    async with clean_db.acquire() as conn:
        u = await _insert_user(conn, "sub-1", "a@b.c")
        w = await _insert_wallet(conn, u, "w")

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO wallet_tags (wallet_id, tag) VALUES ($1::uuid, 'PROD')",
                w,
            )


async def test_kdf_floors_enforced_on_users(clean_db: asyncpg.Pool) -> None:
    async with clean_db.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO users (
                    keycloak_sub, email, rsa_public_key,
                    salt_passphrase, salt_recovery,
                    encrypted_rsa_private_key, encrypted_sym_key_by_pass,
                    encrypted_sym_key_by_recovery,
                    kdf_memory_kb, kdf_iterations, kdf_parallelism, rsa_key_size
                )
                VALUES (
                    'sub-low', 'low@b.c', '\\x00', '\\x00', '\\x00',
                    '\\x00', '\\x00', '\\x00',
                    1024, 3, 4, 2048
                )
                """
            )


async def test_rsa_key_size_must_be_2048_or_4096(clean_db: asyncpg.Pool) -> None:
    async with clean_db.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO users (
                    keycloak_sub, email, rsa_public_key,
                    salt_passphrase, salt_recovery,
                    encrypted_rsa_private_key, encrypted_sym_key_by_pass,
                    encrypted_sym_key_by_recovery,
                    kdf_memory_kb, kdf_iterations, kdf_parallelism, rsa_key_size
                )
                VALUES (
                    'sub-rsa', 'rsa@b.c', '\\x00', '\\x00', '\\x00',
                    '\\x00', '\\x00', '\\x00',
                    65536, 3, 4, 1024
                )
                """
            )
