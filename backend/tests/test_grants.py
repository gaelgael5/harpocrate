"""Tests des endpoints /v1/wallets/{id}/grants/* — LOT_04."""
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
_GRANTEE_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
_OWNER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")  # même que _CALLER_ID par défaut
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_GRANT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_OWNER_GRANT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")

# permissions 63 = 0x3F = all bits
_PERM_ALL = 63
# permissions 5 = read|init
_PERM_READ_INIT = 5
# permissions 32 = share only
_PERM_SHARE_ONLY = 32

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
    email: str = "alice@example.com",
) -> FakeRecord:
    return FakeRecord(
        {
            "id": user_id,
            "keycloak_sub": sub,
            "email": email,
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
    owner_user_id: uuid.UUID = _OWNER_ID,
    permissions: int = _PERM_ALL,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": wallet_id,
            "name": "Test Wallet",
            "description": None,
            "owner_user_id": owner_user_id,
            "created_at": _NOW,
            "updated_at": _NOW,
            "my_permissions": permissions,
            "valued_secrets_count": 0,
            "placeholder_secrets_count": 0,
            "deleted_at": None,
        }
    )


def _fake_grant_row(
    *,
    grant_id: uuid.UUID = _GRANT_ID,
    grantee_user_id: uuid.UUID = _GRANTEE_ID,
    permissions: int = _PERM_READ_INIT,
    wallet_id: uuid.UUID = _WALLET_ID,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": grant_id,
            "wallet_id": wallet_id,
            "grantee_user_id": grantee_user_id,
            "permissions": permissions,
            "granted_by_user_id": _CALLER_ID,
            "granted_at": _NOW,
            "email": "bob@example.com",
            "display_name": "Bob",
        }
    )


def _fake_my_grant_row(
    *,
    grant_id: uuid.UUID = _GRANT_ID,
    grantee_user_id: uuid.UUID = _CALLER_ID,
    permissions: int = _PERM_ALL,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": grant_id,
            "grantee_user_id": grantee_user_id,
            "permissions": permissions,
            "encrypted_wallet_key": b"fake_wallet_key",
        }
    )


def _fake_grantee_user(
    user_id: uuid.UUID = _GRANTEE_ID,
    email: str = "bob@example.com",
) -> FakeRecord:
    return FakeRecord(
        {
            "id": user_id,
            "email": email,
            "display_name": "Bob",
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


def _enc_key_b64() -> str:
    return base64.b64encode(b"fake_encrypted_wallet_key_for_grantee").decode()


# ─── test_grant_list_returns_all ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_list_returns_all() -> None:
    """GET /v1/wallets/{id}/grants → 200 avec tous les grants."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # get_wallet_for_user (join wallet_grants)
        return _fake_wallet_row()

    fetch_n = 0

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        # Premier fetch = wallet_tags (depuis get_wallet_for_user) → liste vide
        if fetch_n == 1:
            return []
        # Deuxième fetch = list_grants (JOIN users) → grants
        return [_fake_grant_row(grant_id=_GRANT_ID, grantee_user_id=_GRANTEE_ID)]

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/grants", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert "grants" in body
    assert len(body["grants"]) == 1
    g = body["grants"][0]
    assert g["grantee_user_id"] == str(_GRANTEE_ID)
    assert g["permissions"] == _PERM_READ_INIT
    assert g["is_owner"] is False


# ─── test_grant_list_requires_share_permission ────────────────────────────────


@pytest.mark.asyncio
async def test_grant_list_requires_share_permission() -> None:
    """GET /v1/wallets/{id}/grants → 403 si caller n'a pas [share]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # permissions=1 → read only, pas [share]
        return _fake_wallet_row(owner_user_id=uuid.uuid4(), permissions=1)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/grants", headers=_auth_header())

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "missing_share_permission"


# ─── test_grant_create_happy_path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_create_happy_path() -> None:
    """POST /v1/wallets/{id}/grants → 201 avec grant_id."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            # get_by_keycloak_sub
            return _fake_user_row()
        if call_n == 2:
            # get_wallet_for_user
            return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # get_user_by_id (grantee check)
            return _fake_grantee_user()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetchval = AsyncMock(return_value=_GRANT_ID)  # insert_grant RETURNING id
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/grants",
            json={
                "grantee_user_id": str(_GRANTEE_ID),
                "encrypted_wallet_key_for_grantee": _enc_key_b64(),
                "permissions": _PERM_READ_INIT,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201
    body = r.json()
    assert "grant_id" in body
    assert body["grant_id"] == str(_GRANT_ID)


# ─── test_grant_create_requires_share_permission ──────────────────────────────


@pytest.mark.asyncio
async def test_grant_create_requires_share_permission() -> None:
    """POST /v1/wallets/{id}/grants → 403 si caller n'a pas [share]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(owner_user_id=uuid.uuid4(), permissions=1)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/grants",
            json={
                "grantee_user_id": str(_GRANTEE_ID),
                "encrypted_wallet_key_for_grantee": _enc_key_b64(),
                "permissions": 1,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "missing_share_permission"


# ─── test_grant_create_perms_must_be_subset ───────────────────────────────────


@pytest.mark.asyncio
async def test_grant_create_perms_must_be_subset() -> None:
    """POST /v1/wallets/{id}/grants → 400 si target perms ⊄ caller perms."""
    conn = _make_conn()
    call_n = 0

    # caller a share (0x20) + read (0x01) = 0x21 = 33
    caller_perms = 0x21

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(owner_user_id=uuid.uuid4(), permissions=caller_perms)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/grants",
            json={
                "grantee_user_id": str(_GRANTEE_ID),
                "encrypted_wallet_key_for_grantee": _enc_key_b64(),
                # On tente d'accorder write (0x08) que caller n'a pas
                "permissions": 0x09,  # read + write
            },
            headers=_auth_header(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "permissions_exceed_caller"


# ─── test_grant_create_cannot_share_with_self ─────────────────────────────────


@pytest.mark.asyncio
async def test_grant_create_cannot_share_with_self() -> None:
    """POST /v1/wallets/{id}/grants → 400 si grantee == caller."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/grants",
            json={
                # grantee = caller (même UUID)
                "grantee_user_id": str(_CALLER_ID),
                "encrypted_wallet_key_for_grantee": _enc_key_b64(),
                "permissions": _PERM_READ_INIT,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_share_with_self"


# ─── test_grant_create_grantee_already_has_grant ──────────────────────────────


@pytest.mark.asyncio
async def test_grant_create_grantee_already_has_grant() -> None:
    """POST /v1/wallets/{id}/grants → 409 si grantee a déjà un grant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_grantee_user()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    # Simuler UniqueViolationError au fetchval (INSERT RETURNING)
    conn.fetchval = AsyncMock(
        side_effect=asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
    )

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/grants",
            json={
                "grantee_user_id": str(_GRANTEE_ID),
                "encrypted_wallet_key_for_grantee": _enc_key_b64(),
                "permissions": _PERM_READ_INIT,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "grant_already_exists"


# ─── test_grant_create_grantee_not_found ──────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_create_grantee_not_found() -> None:
    """POST /v1/wallets/{id}/grants → 404 si grantee_user_id inexistant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)
        # grantee lookup → None
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/grants",
            json={
                "grantee_user_id": str(_GRANTEE_ID),
                "encrypted_wallet_key_for_grantee": _enc_key_b64(),
                "permissions": _PERM_READ_INIT,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "grantee_not_found"


# ─── test_grant_update_happy_path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_update_happy_path() -> None:
    """PATCH /v1/wallets/{id}/grants/{grant_id} → 200 avec nouvelles permissions."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            # wallet : caller a permissions=63, owner=caller
            return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # get_grant_by_id : grantee != owner
            return _fake_grant_row(grantee_user_id=_GRANTEE_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/grants/{_GRANT_ID}",
            json={"permissions": 7},  # read|add|init
            headers=_auth_header(),
        )

    assert r.status_code == 200
    conn.execute.assert_awaited()


# ─── test_grant_update_owner_protected ────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_update_owner_protected() -> None:
    """PATCH /v1/wallets/{id}/grants/{grant_id} → 403 si grant = owner."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            # wallet : owner = some other user, caller a [share]=63
            return _fake_wallet_row(owner_user_id=_GRANTEE_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # grant : grantee == owner → protégé
            return _fake_grant_row(grant_id=_OWNER_GRANT_ID, grantee_user_id=_GRANTEE_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/grants/{_OWNER_GRANT_ID}",
            json={"permissions": 7},
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "owner_grant_immutable"


# ─── test_grant_delete_happy_path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_delete_happy_path() -> None:
    """DELETE /v1/wallets/{id}/grants/{grant_id} → 204."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # grant : grantee != owner
            return _fake_grant_row(grantee_user_id=_GRANTEE_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/grants/{_GRANT_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 204
    conn.execute.assert_awaited()


# ─── test_grant_delete_owner_protected ────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_delete_owner_protected() -> None:
    """DELETE /v1/wallets/{id}/grants/{grant_id} → 403 si grant = owner."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            # wallet owner = _GRANTEE_ID, caller a [share]
            return _fake_wallet_row(owner_user_id=_GRANTEE_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # grant cible : grantee == owner
            return _fake_grant_row(grant_id=_OWNER_GRANT_ID, grantee_user_id=_GRANTEE_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/grants/{_OWNER_GRANT_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "owner_grant_immutable"


# ─── test_my_grant_returns_caller_grant ───────────────────────────────────────


@pytest.mark.asyncio
async def test_my_grant_returns_caller_grant() -> None:
    """GET /v1/wallets/{id}/my-grant → 200 avec grant du caller."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            # get_wallet_for_user
            return _fake_wallet_row(owner_user_id=_CALLER_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # get_my_grant
            return _fake_my_grant_row(grantee_user_id=_CALLER_ID, permissions=_PERM_ALL)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/my-grant",
            headers=_auth_header(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["permissions"] == _PERM_ALL
    assert body["is_owner"] is True
    assert "encrypted_wallet_key" in body


# ─── test_my_grant_returns_404_if_no_grant ────────────────────────────────────


@pytest.mark.asyncio
async def test_my_grant_returns_404_if_no_grant() -> None:
    """GET /v1/wallets/{id}/my-grant → 404 si pas de grant pour le caller."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # get_wallet_for_user → None (pas de grant → wallet invisible)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/my-grant",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "wallet_not_found"


# ─── test_grant_update_perms_must_be_subset ───────────────────────────────────


@pytest.mark.asyncio
async def test_grant_update_perms_must_be_subset() -> None:
    """PATCH /v1/wallets/{id}/grants/{grant_id} → 400 si permissions ⊄ caller."""
    conn = _make_conn()
    call_n = 0

    # caller a share+read = 0x21
    caller_perms = 0x21

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(owner_user_id=uuid.uuid4(), permissions=caller_perms)
        if call_n == 3:
            return _fake_grant_row(grantee_user_id=_GRANTEE_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}/grants/{_GRANT_ID}",
            # On tente d'accorder write (0x08) que caller n'a pas
            json={"permissions": 0x09},
            headers=_auth_header(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "permissions_exceed_caller"
