"""Tests des endpoints /v1/wallets/* et /v1/users/lookup — LOT_03."""
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

# ─── Fixtures d'environnement ─────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER2_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_GRANT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security

    _sec_settings = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec_settings, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec_settings, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec_settings, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


@pytest.fixture(autouse=True)
def reset_rate_limit() -> Generator[None, None, None]:
    """Réinitialise le rate-limiter in-memory entre chaque test."""
    from app.services import wallets as wallets_svc

    wallets_svc._lookup_attempts.clear()
    yield
    wallets_svc._lookup_attempts.clear()


# ─── FakeRecord ───────────────────────────────────────────────────────────────


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _fake_user_row() -> FakeRecord:
    return FakeRecord(
        {
            "id": _USER_ID,
            "keycloak_sub": "test-sub-001",
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
    owner_user_id: uuid.UUID = _USER_ID,
    permissions: int = 63,
    name: str = "My Wallet",
) -> FakeRecord:
    return FakeRecord(
        {
            "id": wallet_id,
            "name": name,
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


def _fake_tag_row(wallet_id: uuid.UUID, tag: str) -> FakeRecord:
    return FakeRecord({"wallet_id": wallet_id, "tag": tag})


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
    return base64.b64encode(b"fake_encrypted_wallet_key").decode()


# ─── test_wallet_create_happy_path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_create_happy_path() -> None:
    """POST /v1/wallets → 201, wallet_id présent, grant owner créé."""
    conn = _make_conn()
    # get_by_keycloak_sub → fetchrow retourne l'utilisateur
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())
    # insert wallet → fetchval retourne le wallet_id
    conn.fetchval = AsyncMock(return_value=_WALLET_ID)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets",
            json={
                "name": "My Wallet",
                "description": "Test wallet",
                "tags": ["prod", "agflow"],
                "encrypted_wallet_key_for_owner": _enc_key_b64(),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201
    body = r.json()
    assert "wallet_id" in body
    # Vérifie que l'execute pour le grant a bien été appelé
    conn.execute.assert_awaited()


# ─── test_wallet_list_empty ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_list_empty() -> None:
    """GET /v1/wallets → 200 avec items vide."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/wallets", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert body["wallets"] == []
    assert body["next_cursor"] is None


# ─── test_wallet_list_pagination_cursor ───────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_list_pagination_cursor() -> None:
    """GET /v1/wallets avec limit=1 sur 2 wallets → next_cursor non None, puis None."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    w1_id = uuid.uuid4()
    w2_id = uuid.uuid4()
    now = _NOW
    earlier = _NOW - datetime.timedelta(seconds=1)

    wallet_rows = [
        _fake_wallet_row(wallet_id=w1_id, name="Wallet 1"),
        _fake_wallet_row(wallet_id=w2_id, name="Wallet 2"),
    ]
    # Mettre des updated_at différents pour le curseur
    wallet_rows[0]["updated_at"] = now
    wallet_rows[1]["updated_at"] = earlier

    call_count = 0

    async def fetch_side_effect(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal call_count
        # premier appel = listage wallets (2 rows pour limit=1+1=2)
        if "wallet_tags" in query and "ANY" in query:
            return []
        call_count += 1
        if call_count == 1:
            return wallet_rows  # retourne limit+1 = 2 pour limit=1
        return []

    conn.fetch = fetch_side_effect

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/wallets?limit=1", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert len(body["wallets"]) == 1
    assert body["next_cursor"] is not None

    # Passe le cursor
    cursor = body["next_cursor"]
    call_count = 0

    async def fetch_page2(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal call_count
        if "wallet_tags" in query and "ANY" in query:
            return []
        call_count += 1
        return []

    conn.fetch = fetch_page2

    async with _make_client(_make_pool(conn)) as client:
        r2 = await client.get(f"/v1/wallets?limit=1&cursor={cursor}", headers=_auth_header())

    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["next_cursor"] is None


# ─── test_wallet_get_not_found ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_get_not_found() -> None:
    """GET /v1/wallets/{id} → 404 si wallet inexistant ou pas de grant."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())
    # get_wallet_for_user retourne None (join wallet_grants échoue)
    # fetchrow est appelé deux fois : 1) get_by_keycloak_sub, 2) get_wallet_for_user
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return None

    conn.fetchrow = fetchrow_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}", headers=_auth_header())

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "wallet_not_found"


# ─── test_wallet_get_no_grant ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_get_no_grant() -> None:
    """GET /v1/wallets/{id} → 404 si wallet existe mais caller n'a pas de grant."""
    # Le comportement est identique à not_found par design (ne pas révéler l'existence)
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # Pas de grant → None
        return None

    conn.fetchrow = fetchrow_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}", headers=_auth_header())

    assert r.status_code == 404


# ─── test_wallet_patch_requires_owner_or_share ────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_patch_requires_owner_or_share() -> None:
    """PATCH /v1/wallets/{id} → 403 si caller n'a pas owner ni share bit."""
    conn = _make_conn()
    # caller a permissions=1 (read only, pas owner, pas share)
    other_owner = uuid.uuid4()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(owner_user_id=other_owner, permissions=1)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}",
            json={"name": "New Name"},
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "forbidden"


# ─── test_wallet_delete_requires_exact_name_confirmation ──────────────────────


@pytest.mark.asyncio
async def test_wallet_delete_requires_exact_name_confirmation() -> None:
    """DELETE /v1/wallets/{id} → 400 si confirmation != wallet name exact."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(name="My Wallet")

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.request(
            "DELETE",
            f"/v1/wallets/{_WALLET_ID}",
            json={"confirmation": "my wallet"},  # mauvaise casse
            headers=_auth_header(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "confirmation_mismatch"


# ─── test_wallet_delete_happy_path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_delete_happy_path() -> None:
    """DELETE /v1/wallets/{id} → 204 si owner et confirmation correcte."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(name="My Wallet", owner_user_id=_USER_ID)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.request(
            "DELETE",
            f"/v1/wallets/{_WALLET_ID}",
            json={"confirmation": "My Wallet"},
            headers=_auth_header(),
        )

    assert r.status_code == 204
    # Vérification que le DELETE a bien été exécuté
    conn.execute.assert_awaited()


# ─── test_wallet_transfer_ownership_changes_owner ─────────────────────────────


@pytest.mark.asyncio
async def test_wallet_transfer_ownership_changes_owner() -> None:
    """POST /v1/wallets/{id}/transfer-ownership → 200, new owner, old owner garde grant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            # get_by_keycloak_sub
            return _fake_user_row()
        if call_n == 2:
            # get_wallet_for_user (old owner)
            return _fake_wallet_row(owner_user_id=_USER_ID)
        if call_n == 3:
            # get_wallet_for_user après transfert (old owner toujours grantee)
            return _fake_wallet_row(owner_user_id=_USER2_ID, permissions=32)
        return None

    async def fetchval_side(query: str, *args: Any) -> Any:
        # grant_exists → 1 (le new owner a un grant)
        return 1

    conn.fetchrow = fetchrow_side
    conn.fetchval = fetchval_side

    async def fetch_side(query: str, *args: Any) -> list[Any]:
        return []

    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/transfer-ownership",
            json={"new_owner_user_id": str(_USER2_ID)},
            headers=_auth_header(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["owner_user_id"] == str(_USER2_ID)
    assert body["is_owner"] is False  # caller (_USER_ID) n'est plus owner


# ─── test_users_lookup_returns_match ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_lookup_returns_match() -> None:
    """GET /v1/users/lookup?email=... → 200 avec user info et rsa_public_key."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            # get_by_keycloak_sub (caller bootstrap check)
            return _fake_user_row()
        if call_n == 2:
            # get_user_by_email
            return FakeRecord(
                {
                    "id": _USER2_ID,
                    "email": "bob@example.com",
                    "display_name": "Bob Test",
                    "rsa_public_key": b"fake_rsa_public_key",
                }
            )
        return None

    conn.fetchrow = fetchrow_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            "/v1/users/lookup?email=bob@example.com",
            headers=_auth_header(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "bob@example.com"
    assert body["display_name"] == "Bob Test"
    assert "rsa_public_key" in body
    assert "user_id" in body


# ─── test_users_lookup_rate_limit ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_lookup_rate_limit() -> None:
    """GET /v1/users/lookup → 429 après 30 appels depuis la même IP."""
    from time import monotonic

    from app.services import wallets as wallets_svc

    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    # ASGITransport utilise 127.0.0.1 comme IP client par défaut
    ip = "127.0.0.1"
    wallets_svc._lookup_attempts[ip] = [monotonic() for _ in range(30)]

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            "/v1/users/lookup?email=bob@example.com",
            headers=_auth_header(),
        )

    assert r.status_code == 429
    assert r.json()["detail"]["error"] == "rate_limit_exceeded"


# ─── test_wallet_list_is_owner_field ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_list_is_owner_field() -> None:
    """GET /v1/wallets : is_owner basé sur owner_user_id, pas sur permissions."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    other_owner = uuid.uuid4()
    wallet_row = _fake_wallet_row(owner_user_id=other_owner, permissions=63)

    call_n = 0

    async def fetch_side(query: str, *args: Any) -> list[Any]:
        nonlocal call_n
        call_n += 1
        if "wallet_tags" in query and "ANY" in query:
            return []
        return [wallet_row]

    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/wallets", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert len(body["wallets"]) == 1
    # caller _USER_ID n'est pas owner_user_id=other_owner, donc is_owner=False
    # même si permissions=63
    assert body["wallets"][0]["is_owner"] is False


# ─── test_wallet_delete_not_owner ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_delete_not_owner() -> None:
    """DELETE /v1/wallets/{id} → 403 si caller n'est pas owner."""
    conn = _make_conn()
    call_n = 0
    other_owner = uuid.uuid4()

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(owner_user_id=other_owner, permissions=32)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.request(
            "DELETE",
            f"/v1/wallets/{_WALLET_ID}",
            json={"confirmation": "My Wallet"},
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_owner"


# ─── test_wallet_transfer_requires_existing_grant ─────────────────────────────


@pytest.mark.asyncio
async def test_wallet_transfer_requires_existing_grant() -> None:
    """POST /v1/wallets/{id}/transfer-ownership → 400 si new owner n'a pas de grant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(owner_user_id=_USER_ID)

    async def fetchval_side(query: str, *args: Any) -> Any:
        # grant_exists → None (pas de grant pour new owner)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetchval = fetchval_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/transfer-ownership",
            json={"new_owner_user_id": str(_USER2_ID)},
            headers=_auth_header(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "new_owner_has_no_grant"


# ─── test_wallet_patch_happy_path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_patch_happy_path() -> None:
    """PATCH /v1/wallets/{id} → 200 si owner."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # Wallet avec owner = caller et permissions=63
        return _fake_wallet_row(owner_user_id=_USER_ID, name="Old Name")

    conn.fetchrow = fetchrow_side

    async def fetch_side(query: str, *args: Any) -> list[Any]:
        return []

    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/wallets/{_WALLET_ID}",
            json={"name": "New Name"},
            headers=_auth_header(),
        )

    assert r.status_code == 200
    body = r.json()
    assert "id" in body
