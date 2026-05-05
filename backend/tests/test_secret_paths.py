"""Tests LOT_18 — secret paths : trigger index, validation, repo, endpoints.

Tests d'intégration DB : nécessitent HARPOCRATE_DB_DSN_TEST=postgresql://...
Tests unitaires (validation) : aucune DB requise.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from app.db.repositories.secrets import get_tree_data, list_by_path
from app.services.secret_paths import InvalidSecretPath, normalize_path, validate_secret_name

pytestmark = pytest.mark.asyncio

_INSERT_SECRET_SQL = (
    "INSERT INTO secrets "
    "(wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)"
    " VALUES ($1, $2, '\\xDEAD', FALSE, $3) RETURNING id"
)

_INSERT_SECRET_FIXED_SQL = (
    "INSERT INTO secrets "
    "(wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)"
    " VALUES ($1, $2, '\\xDEAD', FALSE, $4) RETURNING id"
)

# ─── Fixtures DB d'intégration ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_conn(real_db_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Connexion dans une transaction rollbackée après chaque test."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        yield conn
        await tr.rollback()


@pytest_asyncio.fixture
async def user_fixture(db_conn: asyncpg.Connection) -> UUID:
    """Insère un user de test et retourne son UUID."""
    user_id = cast(
        UUID,
        await db_conn.fetchval(
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
            ) RETURNING id
            """,
            f"sub-{uuid.uuid4()}",
            f"test-{uuid.uuid4()}@example.com",
        ),
    )
    return user_id


@pytest_asyncio.fixture
async def wallet_fixture(db_conn: asyncpg.Connection, user_fixture: UUID) -> UUID:
    """Insère un wallet de test et retourne son UUID."""
    wallet_id = cast(
        UUID,
        await db_conn.fetchval(
            "INSERT INTO wallets (name, owner_user_id) VALUES ($1, $2) RETURNING id",
            f"test-wallet-{uuid.uuid4()}",
            user_fixture,
        ),
    )
    return wallet_id


# ─── Trigger tests ────────────────────────────────────────────────────────────


_TRIGGER_SQL = (
    "INSERT INTO secrets "
    "(wallet_id, name, encrypted_value, is_placeholder, created_by_user_id) "
    "VALUES ($1, $2, '\\xDEAD', FALSE, $3) RETURNING id"
)


async def test_trigger_no_index_for_root_secret(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    """Un secret sans '/' ne crée aucune ligne dans secret_path_index."""
    secret_id = await db_conn.fetchval(
        _TRIGGER_SQL, wallet_fixture, "PLAIN_SECRET", user_fixture
    )
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM secret_path_index WHERE secret_id = $1", secret_id
    )
    assert count == 0


async def test_trigger_populates_index_for_two_level_secret(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    """Un secret '/bob/key' crée 1 ligne (depth=1, path_segment='/bob/')."""
    secret_id = await db_conn.fetchval(
        _TRIGGER_SQL, wallet_fixture, "/bob/key", user_fixture
    )
    rows = await db_conn.fetch(
        "SELECT path_segment, depth FROM secret_path_index"
        " WHERE secret_id = $1 ORDER BY depth",
        secret_id,
    )
    assert len(rows) == 1
    assert rows[0]["path_segment"] == "/bob/"
    assert rows[0]["depth"] == 1


async def test_trigger_populates_index_for_three_level_secret(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    """Un secret '/bob/sub/key' crée 2 lignes (depth=1 et depth=2)."""
    secret_id = await db_conn.fetchval(
        _TRIGGER_SQL, wallet_fixture, "/bob/sub/key", user_fixture
    )
    rows = await db_conn.fetch(
        "SELECT path_segment, depth FROM secret_path_index"
        " WHERE secret_id = $1 ORDER BY depth",
        secret_id,
    )
    assert len(rows) == 2
    assert rows[0]["path_segment"] == "/bob/"
    assert rows[1]["path_segment"] == "/bob/sub/"


async def test_trigger_updates_index_on_rename(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    """Renommer un secret met à jour l'index."""
    secret_id = await db_conn.fetchval(
        _TRIGGER_SQL, wallet_fixture, "/bob/old_key", user_fixture
    )
    await db_conn.execute(
        "UPDATE secrets SET name = '/alice/new_key' WHERE id = $1", secret_id
    )
    rows = await db_conn.fetch(
        "SELECT path_segment FROM secret_path_index WHERE secret_id = $1", secret_id
    )
    assert len(rows) == 1
    assert rows[0]["path_segment"] == "/alice/"


async def test_trigger_cleans_index_on_delete(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    """Supprimer un secret efface ses lignes d'index (CASCADE)."""
    secret_id = await db_conn.fetchval(
        _TRIGGER_SQL, wallet_fixture, "/folder/key", user_fixture
    )
    await db_conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM secret_path_index WHERE secret_id = $1", secret_id
    )
    assert count == 0


# ─── Validation tests ─────────────────────────────────────────────────────────


def test_validate_accepts_root_secret() -> None:
    assert validate_secret_name("MY_SECRET") == "MY_SECRET"


def test_validate_accepts_single_level_path() -> None:
    assert validate_secret_name("bob/key") == "/bob/key"


def test_validate_normalizes_leading_slash() -> None:
    assert validate_secret_name("/bob/key") == "/bob/key"


def test_validate_accepts_email_segment() -> None:
    assert validate_secret_name("bob@gmail.com/key") == "/bob@gmail.com/key"


def test_validate_rejects_empty_segment() -> None:
    with pytest.raises(InvalidSecretPath, match="[Ee]mpty"):  # noqa: RUF043
        validate_secret_name("bob//key")


def test_validate_rejects_dot_segment() -> None:
    with pytest.raises(InvalidSecretPath, match="[Rr]elative"):  # noqa: RUF043
        validate_secret_name("bob/../key")


def test_validate_rejects_invalid_char() -> None:
    with pytest.raises(InvalidSecretPath, match="[Ii]nvalid"):  # noqa: RUF043
        validate_secret_name("bob/key with space")


def test_validate_rejects_too_deep() -> None:
    deep = "/".join(["a"] * 13)
    with pytest.raises(InvalidSecretPath, match="deep"):
        validate_secret_name(deep)


def test_validate_secret_name_rejects_trailing_slash() -> None:
    """Un nom qui finit par '/' est invalide (sinon il apparaît comme un dossier dans le tree)."""
    with pytest.raises(InvalidSecretPath, match="trailing"):
        validate_secret_name("/foo/bar/")


def test_validate_secret_name_rejects_trailing_slash_without_leading() -> None:
    """Même rejet pour les noms sans slash initial qui finissent par /."""
    with pytest.raises(InvalidSecretPath, match="trailing"):
        validate_secret_name("foo/bar/")


def test_normalize_path_adds_trailing_slash() -> None:
    assert normalize_path("/bob") == "/bob/"


def test_normalize_path_root() -> None:
    assert normalize_path("/") == "/"
    assert normalize_path("") == "/"


# ─── Repo tests ───────────────────────────────────────────────────────────────


async def _insert_secret(
    conn: asyncpg.Connection, wallet_id: UUID, user_id: UUID, name: str
) -> UUID:
    return cast(
        UUID,
        await conn.fetchval(
            "INSERT INTO secrets "
            "(wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)"
            " VALUES ($1, $2, '\\xDEAD', FALSE, $3) RETURNING id",
            wallet_id, name, user_id,
        ),
    )


async def test_list_by_path_root_returns_only_root_secrets(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "ROOT_SECRET")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/nested")
    rows = await list_by_path(
        db_conn, wallet_id=wallet_fixture, path="/",
        limit=50, cursor_updated_at=None, cursor_id=None,
    )
    names = [r.name for r in rows]
    assert "ROOT_SECRET" in names
    assert "/bob/nested" not in names


async def test_list_by_path_folder_excludes_subfolders(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/direct_key")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/sub/nested_key")
    rows = await list_by_path(
        db_conn, wallet_id=wallet_fixture, path="/bob/",
        limit=50, cursor_updated_at=None, cursor_id=None,
    )
    names = [r.name for r in rows]
    assert "/bob/direct_key" in names
    assert "/bob/sub/nested_key" not in names


async def test_get_tree_data_root(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "ROOT_SECRET")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/key")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/alice/key")
    result = await get_tree_data(db_conn, wallet_id=wallet_fixture, path="/")
    assert result["path"] == "/"
    assert result["secrets_at_this_level_count"] == 1
    folder_names = [f["name"] for f in result["folders"]]  # type: ignore[index]
    assert "bob" in folder_names
    assert "alice" in folder_names


async def test_get_tree_data_subfolder(
    db_conn: asyncpg.Connection, wallet_fixture: UUID, user_fixture: UUID
) -> None:
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/key1")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/key2")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/sub/deep_key")
    result = await get_tree_data(db_conn, wallet_id=wallet_fixture, path="/bob/")
    assert result["secrets_at_this_level_count"] == 2
    assert len(result["folders"]) == 1  # type: ignore[arg-type]
    assert result["folders"][0]["name"] == "sub"  # type: ignore[index]
