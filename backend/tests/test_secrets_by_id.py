"""Tests des routes /v1/wallets/{wid}/secrets/by-id/{sid} — accès par UUID
pour les secrets dont le nom contient des '/' (path-style names).
"""

from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_OTHER_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000099")
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

_PERM_ALL = 63
_PERM_READ_ONLY = 1
_PERM_NO_READ = 62

_FAKE_ENC_VALUE = b"fake_encrypted_secret_value"
_FAKE_ENC_KEY = b"fake_encrypted_wallet_key_for_caller"
_FAKE_ENC_VALUE_B64 = base64.b64encode(_FAKE_ENC_VALUE).decode()


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _fake_user_row() -> FakeRecord:
    return FakeRecord(
        {
            "id": _CALLER_ID,
            "keycloak_sub": "test-sub-001",
            "email": "alice@example.com",
            "display_name": "Alice",
            "rsa_public_key": b"x",
            "salt_passphrase": b"x" * 16,
            "salt_recovery": b"y" * 16,
            "encrypted_rsa_private_key": b"x",
            "encrypted_sym_key_by_pass": b"x",
            "encrypted_sym_key_by_recovery": b"x",
            "kdf_memory_kb": 65536,
            "kdf_iterations": 3,
            "kdf_parallelism": 4,
            "rsa_key_size": 2048,
            "created_at": _NOW,
            "updated_at": _NOW,
            "last_unlock_at": None,
        }
    )


def _fake_wallet_row(wallet_id: uuid.UUID = _WALLET_ID, permissions: int = _PERM_ALL) -> FakeRecord:
    return FakeRecord(
        {
            "id": wallet_id,
            "name": "Test Wallet",
            "description": None,
            "owner_user_id": _CALLER_ID,
            "created_at": _NOW,
            "updated_at": _NOW,
            "my_permissions": permissions,
            "valued_secrets_count": 0,
            "placeholder_secrets_count": 0,
            "deleted_at": None,
        }
    )


def _fake_secret_row(
    *,
    secret_id: uuid.UUID = _SECRET_ID,
    wallet_id: uuid.UUID = _WALLET_ID,
    name: str = "/users/no_email/transcription/openai-whisper/api-1",
    is_placeholder: bool = False,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": secret_id,
            "wallet_id": wallet_id,
            "name": name,
            "description": None,
            "encrypted_value": _FAKE_ENC_VALUE,
            "is_placeholder": is_placeholder,
            "generation_version": 1,
            "generation_descriptor": None,
            "linked_secret_id": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            "created_by_user_id": _CALLER_ID,
            "created_by_api_key_id": None,
            "updated_by_user_id": None,
            "updated_by_api_key_id": None,
        }
    )


class _FakeTxCtx:
    async def __aenter__(self) -> _FakeTxCtx:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    conn.executemany = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=_FakeTxCtx())
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


# ─── GET /by-id/{sid} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_by_id_happy_path() -> None:
    """GET by-id retourne le secret avec encrypted_value et encrypted_wallet_key."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()  # get_secret_by_id
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])  # tags
    conn.fetchval = AsyncMock(return_value=_FAKE_ENC_KEY)  # encrypted_wallet_key

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(_SECRET_ID)
    assert body["name"] == "/users/no_email/transcription/openai-whisper/api-1"
    assert body["encrypted_value"] == _FAKE_ENC_VALUE_B64
    assert body["encrypted_wallet_key"] == base64.b64encode(_FAKE_ENC_KEY).decode()


@pytest.mark.asyncio
async def test_get_by_id_cross_wallet_returns_404() -> None:
    """Un secret qui appartient à un autre wallet → 404 (ne pas leak l'existence)."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # Le secret existe mais dans un AUTRE wallet
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"


@pytest.mark.asyncio
async def test_get_by_id_requires_read_permission() -> None:
    """403 si le caller n'a pas [read]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_NO_READ)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"


@pytest.mark.asyncio
async def test_get_by_id_returns_404_when_secret_does_not_exist() -> None:
    """404 si l'UUID ne correspond à aucun secret."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        return None  # secret introuvable

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"


# ─── PUT /by-id/{sid} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_by_id_happy_path() -> None:
    """PUT by-id remplace encrypted_value et incrémente generation_version."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()  # get_secret_by_id
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])
    # update_secret_value retourne la nouvelle generation_version
    conn.fetchval = AsyncMock(return_value=2)

    new_value_b64 = base64.b64encode(b"new_encrypted_value").decode()

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"encrypted_value": new_value_b64},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json()["generation_version"] == 2


@pytest.mark.asyncio
async def test_put_by_id_cross_wallet_returns_404() -> None:
    """PUT sur un secret d'un autre wallet → 404."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"encrypted_value": _FAKE_ENC_VALUE_B64},
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"


@pytest.mark.asyncio
async def test_put_by_id_requires_write_permission() -> None:
    """403 si le caller n'a pas [write]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # Tout sauf write (PERM_WRITE = 0x08)
        return _fake_wallet_row(permissions=_PERM_ALL & ~0x08)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"encrypted_value": _FAKE_ENC_VALUE_B64},
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"


# ─── DELETE /by-id/{sid} ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_by_id_happy_path() -> None:
    """DELETE by-id retourne 204 et exécute la suppression."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 204, r.text
    # Vérifie qu'un DELETE SQL a été émis
    assert any("DELETE FROM secrets" in str(c.args[0]) for c in conn.execute.call_args_list)


@pytest.mark.asyncio
async def test_delete_by_id_cross_wallet_returns_404() -> None:
    """DELETE sur un secret d'un autre wallet → 404."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    # Vérifie qu'aucun DELETE SQL n'a été émis (le secret n'a pas été touché)
    assert not any("DELETE FROM secrets" in str(c.args[0]) for c in conn.execute.call_args_list)


@pytest.mark.asyncio
async def test_delete_by_id_requires_remove_permission() -> None:
    """403 si le caller n'a pas [remove]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # Tout sauf remove (0x10 = 16)
        return _fake_wallet_row(permissions=_PERM_ALL & ~16)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"


# ─── PATCH /by-id/{sid} (metadata) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_by_id_happy_path() -> None:
    """PATCH by-id met à jour description/tags."""
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"description": "updated", "tags": ["new"]},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_patch_by_id_cross_wallet_returns_404() -> None:
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"description": "x"},
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"


# ─── POST /by-id/{sid}/populate ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_populate_by_id_happy_path() -> None:
    """POST /by-id/{sid}/populate sur un placeholder → 200."""
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(is_placeholder=True)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=2)  # new generation_version

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/populate",
            json={"encrypted_value": _FAKE_ENC_VALUE_B64},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json()["generation_version"] == 2


@pytest.mark.asyncio
async def test_populate_by_id_cross_wallet_returns_404() -> None:
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID, is_placeholder=True)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/populate",
            json={"encrypted_value": _FAKE_ENC_VALUE_B64},
            headers=_auth_header(),
        )

    assert r.status_code == 404


# ─── GET /by-id/{sid}/descriptor ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_descriptor_by_id_happy_path() -> None:
    """GET /by-id/{sid}/descriptor sur un placeholder → 200 avec descriptor."""
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            row = _fake_secret_row(is_placeholder=True)
            row["generation_descriptor"] = {"type": "random", "length": 32}
            return row
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/descriptor",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_placeholder"] is True
    assert body["generation_descriptor"]["type"] == "random"


@pytest.mark.asyncio
async def test_get_descriptor_by_id_on_non_placeholder_returns_404() -> None:
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(is_placeholder=False)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/descriptor",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_placeholder"


@pytest.mark.asyncio
async def test_get_descriptor_by_id_cross_wallet_returns_404() -> None:
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID, is_placeholder=True)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/descriptor",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"


# ─── PATCH /by-id/{sid}/migrate-schema ────────────────────────────────────────


@pytest.mark.asyncio
async def test_migrate_schema_by_id_happy_path() -> None:
    target_version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000010")
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            row = _fake_secret_row()
            row["type_uuid"] = uuid.UUID("eeeeeeee-0000-0000-0000-000000000010")
            return row
        if "secret_schemas" in query and "parent_uuid" in query:
            return FakeRecord({"parent_uuid": uuid.UUID("eeeeeeee-0000-0000-0000-000000000010")})
        if "secret_types" in query and "type_uuid" in query:
            return FakeRecord(
                {
                    "type_uuid": uuid.UUID("eeeeeeee-0000-0000-0000-000000000010"),
                    "current_version_uuid": target_version_uuid,
                    "type": "x",
                    "sous_type": "x",
                    "label": None,
                    "description": None,
                    "is_system": False,
                    "created_by_user_id": None,
                    "created_at": _NOW,
                    "updated_at": _NOW,
                    "deprecated_at": None,  # active
                    "cv_version": 2,
                    "cv_schema_data": "{}",
                    "cv_schema_ui": "{}",
                    "cv_created_at": _NOW,
                    "used_count": 0,
                }
            )
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/migrate-schema",
            json={
                "encrypted_value": _FAKE_ENC_VALUE_B64,
                "target_schema_version_uuid": str(target_version_uuid),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"migrated": True}


@pytest.mark.asyncio
async def test_migrate_schema_by_id_cross_wallet_returns_404() -> None:
    target_version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000010")
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/migrate-schema",
            json={
                "encrypted_value": _FAKE_ENC_VALUE_B64,
                "target_schema_version_uuid": str(target_version_uuid),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 404


# ─── PATCH /by-id/{sid}/assign-type ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_type_by_id_happy_path() -> None:
    target_type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000020")
    target_version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000020")
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()
        if "secret_schemas" in query and "parent_uuid" in query:
            return FakeRecord({"parent_uuid": target_type_uuid})
        if "secret_types" in query and "type_uuid" in query:
            return FakeRecord(
                {
                    "type_uuid": target_type_uuid,
                    "current_version_uuid": target_version_uuid,
                    "type": "x",
                    "sous_type": "x",
                    "label": None,
                    "description": None,
                    "is_system": False,
                    "created_by_user_id": None,
                    "created_at": _NOW,
                    "updated_at": _NOW,
                    "deprecated_at": None,
                    "cv_version": 1,
                    "cv_schema_data": "{}",
                    "cv_schema_ui": "{}",
                    "cv_created_at": _NOW,
                    "used_count": 0,
                }
            )
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/assign-type",
            json={
                "type_uuid": str(target_type_uuid),
                "schema_version_uuid": str(target_version_uuid),
                "encrypted_value": _FAKE_ENC_VALUE_B64,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"assigned": True}


@pytest.mark.asyncio
async def test_assign_type_by_id_cross_wallet_returns_404() -> None:
    target_type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000020")
    target_version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000020")
    conn = _make_conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}/assign-type",
            json={
                "type_uuid": str(target_type_uuid),
                "schema_version_uuid": str(target_version_uuid),
                "encrypted_value": _FAKE_ENC_VALUE_B64,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 404
