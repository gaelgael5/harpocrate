"""Tests des endpoints /v1/wallets/{id}/secrets/* — LOT_05."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Constantes de test ───────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_SECRET_ID_2 = uuid.UUID("dddddddd-0000-0000-0000-000000000002")

_PERM_ALL = 63
_PERM_READ_ONLY = 1   # 0x01
_PERM_NO_READ = 62    # all except read

_FAKE_ENC_VALUE = base64.b64encode(b"fake_encrypted_secret_value").decode()
_FAKE_ENC_KEY = base64.b64encode(b"fake_encrypted_wallet_key_for_caller").decode()

# ─── Fixtures d'environnement ─────────────────────────────────────────────────


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


# ─── FakeRecord ───────────────────────────────────────────────────────────────


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


# ─── Helpers de fabrication ───────────────────────────────────────────────────


def _fake_user_row(
    user_id: uuid.UUID = _CALLER_ID,
    sub: str = "test-sub-001",
) -> FakeRecord:
    return FakeRecord(
        {
            "id": user_id,
            "keycloak_sub": sub,
            "email": "alice@example.com",
            "display_name": "Alice Test",
            "rsa_public_key": b"fake_rsa_public_key",
            "salt_passphrase": b"x" * 16,
            "salt_recovery": b"y" * 16,
            "encrypted_rsa_private_key": b"fake_enc_priv",
            "encrypted_sym_key_by_pass": b"fake_enc_sym_pass",
            "encrypted_sym_key_by_recovery": b"fake_enc_sym_rec",
            "kdf_memory_kb": 65536,
            "kdf_iterations": 3,
            "kdf_parallelism": 4,
            "rsa_key_size": 2048,
            "created_at": _NOW,
            "updated_at": _NOW,
            "last_unlock_at": None,
        }
    )


def _fake_wallet_row(
    *,
    wallet_id: uuid.UUID = _WALLET_ID,
    permissions: int = _PERM_ALL,
) -> FakeRecord:
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
        }
    )


def _fake_secret_row(
    *,
    secret_id: uuid.UUID = _SECRET_ID,
    name: str = "MY_SECRET",
    enc_value: bytes = b"fake_encrypted_value",
    generation_version: int = 1,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": secret_id,
            "wallet_id": _WALLET_ID,
            "name": name,
            "description": "A secret",
            "encrypted_value": enc_value,
            "is_placeholder": False,
            "generation_version": generation_version,
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
    class _FakeAcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_FakeAcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


# ─── test_secret_create_happy_path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_create_happy_path() -> None:
    """POST /v1/wallets/{id}/secrets → 201 avec secret_id."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # get_wallet_for_user (wallet_grants JOIN)
        return _fake_wallet_row(permissions=_PERM_ALL)

    fetch_n = 0

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []  # wallet_tags ou secret_tags → vide

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side
    conn.fetchval = AsyncMock(return_value=_SECRET_ID)  # INSERT RETURNING id

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_SECRET",
                "description": "A test secret",
                "tags": ["llm"],
                "encrypted_value": _FAKE_ENC_VALUE,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text
    body = r.json()
    assert "secret_id" in body
    assert body["secret_id"] == str(_SECRET_ID)


# ─── test_secret_create_requires_add_permission ───────────────────────────────


@pytest.mark.asyncio
async def test_secret_create_requires_add_permission() -> None:
    """POST /v1/wallets/{id}/secrets → 403 si caller n'a pas [add]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # permissions = read only (0x01), pas add (0x02)
        return _fake_wallet_row(permissions=_PERM_READ_ONLY)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_SECRET",
                "encrypted_value": _FAKE_ENC_VALUE,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "missing_add_permission"


# ─── test_secret_create_invalid_name_regex ────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_create_invalid_name_regex() -> None:
    """POST /v1/wallets/{id}/secrets → 422 si nom contient des caractères invalides."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY SECRET WITH SPACE",  # espace interdit
                "encrypted_value": _FAKE_ENC_VALUE,
            },
            headers=_auth_header(),
        )

    # 422 = Unprocessable Entity (validation Pydantic)
    assert r.status_code == 422


# ─── test_secret_create_value_too_large ───────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_create_value_too_large() -> None:
    """POST /v1/wallets/{id}/secrets → 422 si encrypted_value dépasse 5 MB décodé."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    # 5 MB + 1 octet de données brutes → dépasse la limite
    oversized_bytes = b"x" * (5 * 1024 * 1024 + 1)
    oversized_b64 = base64.b64encode(oversized_bytes).decode()

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "BIG_SECRET",
                "encrypted_value": oversized_b64,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 422  # Pydantic validation → 422


# ─── test_secret_create_duplicate_name ───────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_create_duplicate_name() -> None:
    """POST /v1/wallets/{id}/secrets → 409 si nom déjà existant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(
        side_effect=asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
    )

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_SECRET",
                "encrypted_value": _FAKE_ENC_VALUE,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "secret_name_exists"


# ─── test_secret_get_returns_value_and_wallet_key ─────────────────────────────


@pytest.mark.asyncio
async def test_secret_get_returns_value_and_wallet_key() -> None:
    """GET /v1/wallets/{id}/secrets/{name} → 200 avec encrypted_value et encrypted_wallet_key."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        # get_secret_by_name
        if call_n == 3:
            return _fake_secret_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        # 1er fetch : wallet_tags (get_wallet_for_user)
        # 2ème fetch : secret_tags (get_secret_by_name)
        return []

    async def fetchval_side(query: str, *args: Any) -> Any:
        # get_caller_encrypted_wallet_key
        return b"fake_encrypted_wallet_key_for_caller"

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side
    conn.fetchval = fetchval_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY_SECRET",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "encrypted_value" in body
    assert "encrypted_wallet_key" in body
    assert body["name"] == "MY_SECRET"
    assert body["is_placeholder"] is False


# ─── test_secret_get_requires_read_permission ─────────────────────────────────


@pytest.mark.asyncio
async def test_secret_get_requires_read_permission() -> None:
    """GET /v1/wallets/{id}/secrets/{name} → 403 si caller n'a pas [read]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # permissions sans [read] (0x01)
        return _fake_wallet_row(permissions=_PERM_NO_READ)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY_SECRET",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "missing_read_permission"


# ─── test_secret_list_pagination ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_list_pagination() -> None:
    """GET /v1/wallets/{id}/secrets → 200, premier page avec next_cursor, second page vide."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

    secret_row_1 = _fake_secret_row(secret_id=_SECRET_ID, name="SECRET_A")
    secret_row_2 = _fake_secret_row(secret_id=_SECRET_ID_2, name="SECRET_B")

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        if fetch_n == 1:
            # wallet_tags
            return []
        if fetch_n == 2:
            # list_secrets → 2 lignes (limit=2 demandé)
            return [secret_row_1, secret_row_2]
        # secret_tags
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets?limit=2",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["secrets"]) == 2
    # Quand len(résultats) == limit → next_cursor présent
    assert body["next_cursor"] is not None

    # Deuxième page : simuler liste vide
    conn2 = _make_conn()
    call2_n = 0
    fetch2_n = 0

    async def fetchrow2_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call2_n
        call2_n += 1
        if call2_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def fetch2_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch2_n
        fetch2_n += 1
        return []

    conn2.fetchrow = fetchrow2_side
    conn2.fetch = fetch2_side

    cursor = body["next_cursor"]
    async with _make_client(_make_pool(conn2)) as client2:
        r2 = await client2.get(
            f"/v1/wallets/{_WALLET_ID}/secrets?limit=2&cursor={cursor}",
            headers=_auth_header(),
        )

    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2["secrets"]) == 0
    assert body2["next_cursor"] is None


# ─── test_secret_put_updates_value ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_put_updates_value_only_when_not_placeholder() -> None:
    """PUT /v1/wallets/{id}/secrets/{name} → 200 avec generation_version incrémenté."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(generation_version=1)
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side
    conn.fetchval = AsyncMock(return_value=2)  # nouvelle generation_version

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY_SECRET",
            json={"encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generation_version"] == 2


# ─── test_secret_patch_doesnt_modify_value ────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_patch_doesnt_modify_value() -> None:
    """PATCH /v1/wallets/{id}/secrets/{name} → 200, encrypted_value non modifié."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0
    original_value = b"original_encrypted_value"

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(enc_value=original_value)
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY_SECRET",
            json={"description": "Updated description", "tags": ["new-tag"]},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    # Vérifie qu'aucune mise à jour de la valeur n'a été faite
    # (update_secret_value appellerait fetchval — ce dernier n'est pas appelé)
    conn.fetchval.assert_not_called()


# ─── test_secret_delete_happy_path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_delete_happy_path() -> None:
    """DELETE /v1/wallets/{id}/secrets/{name} → 204."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

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

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY_SECRET",
            headers=_auth_header(),
        )

    assert r.status_code == 204
    conn.execute.assert_awaited()


# ─── test_secret_delete_requires_remove_permission ────────────────────────────


@pytest.mark.asyncio
async def test_secret_delete_requires_remove_permission() -> None:
    """DELETE /v1/wallets/{id}/secrets/{name} → 403 si caller n'a pas [remove]."""
    conn = _make_conn()
    call_n = 0

    # PERM_REMOVE = 0x10 = 16 ; on donne tous sauf remove : 63 - 16 = 47
    no_remove_perms = _PERM_ALL & ~0x10  # 47

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=no_remove_perms)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY_SECRET",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "missing_remove_permission"


# ─── test_audit_log_no_value_in_metadata ──────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_no_value_in_metadata() -> None:
    """Vérifie que l'audit log de secret.created ne contient pas encrypted_value."""
    conn = _make_conn()
    call_n = 0
    audit_metadata: dict[str, Any] | None = None

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def execute_side(query: str, *args: Any) -> None:
        nonlocal audit_metadata
        # Capture l'appel audit_log INSERT
        if "INSERT INTO audit_log" in query:
            # args[8] est metadata_json (9ème param, index 8)
            import json
            if len(args) > 8 and args[8] is not None:
                audit_metadata = json.loads(args[8])

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=_SECRET_ID)
    conn.execute = execute_side

    async with _make_client(_make_pool(conn)) as client:
        await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_SECRET",
                "encrypted_value": _FAKE_ENC_VALUE,
            },
            headers=_auth_header(),
        )

    assert audit_metadata is not None, "Audit log n'a pas été appelé"
    assert "encrypted_value" not in audit_metadata, (
        "encrypted_value ne doit JAMAIS apparaître dans les metadata d'audit"
    )
    assert "secret_name" in audit_metadata
    assert audit_metadata["secret_name"] == "MY_SECRET"


# ─── test_secret_list_no_encrypted_value ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_secrets_no_value() -> None:
    """GET /v1/wallets/{id}/secrets → pas de encrypted_value dans les items."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        if fetch_n == 1:
            return []  # wallet_tags
        if fetch_n == 2:
            return [_fake_secret_row()]  # secrets
        return []  # secret_tags

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            headers=_auth_header(),
        )

    assert r.status_code == 200
    body = r.json()
    assert len(body["secrets"]) == 1
    item = body["secrets"][0]
    assert "encrypted_value" not in item
    assert item["name"] == "MY_SECRET"


# ─── test_filter_by_tag ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_tag() -> None:
    """GET /v1/wallets/{id}/secrets?tag=llm → filtre transmis au repo."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0
    captured_tag: str | None = None

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n, captured_tag
        fetch_n += 1
        # args pour list_secrets : ($1=wallet_id, $2=cursor_ts, $3=cursor_id, $4=tag, ...)
        # tag est le 4ème positional arg (index 3)
        if fetch_n == 2 and len(args) >= 4:
            captured_tag = args[3]
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets?tag=llm",
            headers=_auth_header(),
        )

    assert r.status_code == 200
    assert captured_tag == "llm"


# ─── test_body_not_logged ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_body_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    """Vérifie que le middleware log body_logged=False pour les chemins /secrets.

    Structlog écrit en JSON sur stdout ; on capture stdout et on vérifie le champ.
    """
    import json

    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            headers=_auth_header(),
        )

    captured = capsys.readouterr()
    # Chaque ligne de stdout est un objet JSON structlog
    log_lines = [line for line in captured.out.splitlines() if line.strip()]
    import contextlib

    parsed: list[dict[str, Any]] = []
    for line in log_lines:
        with contextlib.suppress(json.JSONDecodeError):
            parsed.append(json.loads(line))

    http_logs = [e for e in parsed if e.get("event") == "http_request"]
    secrets_logs = [
        e for e in http_logs
        if "/secrets" in e.get("path", "") and e.get("body_logged") is False
    ]
    assert secrets_logs, (
        f"Aucun log http_request avec body_logged=False pour /secrets. "
        f"http_request logs: {http_logs}"
    )
