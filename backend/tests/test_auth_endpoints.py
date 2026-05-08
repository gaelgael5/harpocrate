"""Tests des endpoints /v1/me/* — JWT mocké + pool asyncpg mocké."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Fixtures d'environnement ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")
    # Patch le settings référencé par chaque module via sys.modules pour éviter
    # les problèmes de rebinding après importlib.reload dans d'autres fichiers de tests.
    # On importe explicitement pour s'assurer que le module est initialisé.
    import app.core.security
    import app.services.auth

    _sec_settings = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec_settings, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec_settings, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec_settings, "keycloak_client_id", TEST_AUDIENCE)

    _auth_settings = app.services.auth.__dict__["settings"]
    monkeypatch.setattr(_auth_settings, "kdf_memory_kb", 65536)
    monkeypatch.setattr(_auth_settings, "kdf_iterations", 3)
    monkeypatch.setattr(_auth_settings, "kdf_parallelism", 4)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    """Injecte la clé de test dans le cache JWKS pour tous les tests."""
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


# ─── Helper : clé RSA publique valide pour les tests bootstrap ────────────────


def _make_rsa_public_key_b64() -> str:
    """Génère une clé RSA publique valide en DER encodé en base64."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der_bytes = private_key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der_bytes).decode()


def _salt_b64() -> str:
    return base64.b64encode(b"x" * 16).decode()


def _blob_b64() -> str:
    return base64.b64encode(b"fake_encrypted_blob_data").decode()


# ─── Helpers client ───────────────────────────────────────────────────────────


def _make_conn_mock(**fetchrow_side_effects: Any) -> MagicMock:
    """Crée un mock de connexion asyncpg configuré."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)

    # transaction() doit retourner un context manager
    class FakeTxCtx:
        async def __aenter__(self) -> FakeTxCtx:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

    conn.transaction = MagicMock(return_value=FakeTxCtx())
    return conn


def _make_pool_with_conn(conn: MagicMock) -> MagicMock:
    class FakeAcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: object) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=FakeAcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_header(token: str | None = None) -> dict[str, str]:
    t = token or make_jwt_token()
    return {"Authorization": f"Bearer {t}"}


# ─── Données simulées d'un utilisateur bootstrappé ────────────────────────────

_USER_ID = uuid.uuid4()
_KEYCLOAK_SUB = "test-sub-001"
_EMAIL = "alice@example.com"
_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)


def _fake_user_row() -> dict[str, Any]:
    return {
        "id": _USER_ID,
        "keycloak_sub": _KEYCLOAK_SUB,
        "email": _EMAIL,
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


# asyncpg.Record-like : supporte accès par clé
class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


def _fake_record() -> FakeRecord:
    return FakeRecord(_fake_user_row())


# ─── Tests GET /v1/me ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_first_login() -> None:
    """GET /v1/me retourne 404 first_login si pas bootstrappé."""
    conn = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value=None)
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.get("/v1/me", headers=_auth_header())

    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "first_login"
    assert body["details"]["keycloak_sub"] == _KEYCLOAK_SUB


@pytest.mark.asyncio
async def test_me_bootstrapped() -> None:
    """GET /v1/me retourne 200 avec les infos si bootstrappé."""
    conn = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value=_fake_record())
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.get("/v1/me", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert body["keycloak_sub"] == _KEYCLOAK_SUB
    assert body["has_bootstrap"] is True
    assert body["kdf_params"]["memory_kb"] == 65536


# ─── Tests POST /v1/me/bootstrap ─────────────────────────────────────────────


def _bootstrap_payload(
    rsa_pub: str | None = None,
    kdf_memory_kb: int = 65536,
    kdf_iterations: int = 3,
    kdf_parallelism: int = 4,
    rsa_key_size: int = 2048,
    salt: str | None = None,
) -> dict[str, Any]:
    return {
        "rsa_public_key": rsa_pub or _make_rsa_public_key_b64(),
        "salt_passphrase": salt or _salt_b64(),
        "salt_recovery": salt or _salt_b64(),
        "encrypted_rsa_private_key": _blob_b64(),
        "encrypted_sym_key_by_pass": _blob_b64(),
        "encrypted_sym_key_by_recovery": _blob_b64(),
        "kdf_memory_kb": kdf_memory_kb,
        "kdf_iterations": kdf_iterations,
        "kdf_parallelism": kdf_parallelism,
        "rsa_key_size": rsa_key_size,
    }


@pytest.mark.asyncio
async def test_bootstrap_happy_path() -> None:
    """POST /v1/me/bootstrap retourne 201 avec user_id."""
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=_USER_ID)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/me/bootstrap",
            json=_bootstrap_payload(),
            headers=_auth_header(),
        )

    assert r.status_code == 201
    body = r.json()
    assert "user_id" in body


@pytest.mark.asyncio
async def test_bootstrap_kdf_floor_violation() -> None:
    """POST /v1/me/bootstrap avec kdf_memory_kb trop bas retourne 400."""
    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/me/bootstrap",
            json=_bootstrap_payload(kdf_memory_kb=1024),
            headers=_auth_header(),
        )

    assert r.status_code == 400
    # FastAPI enveloppe le detail de HTTPException dans {"detail": {...}}
    body = r.json()
    assert body["detail"]["error"] == "kdf_floor_violation"


@pytest.mark.asyncio
async def test_bootstrap_invalid_rsa_key() -> None:
    """POST /v1/me/bootstrap avec une clé RSA invalide retourne 400."""
    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)

    bad_key = base64.b64encode(b"this_is_not_an_rsa_key").decode()

    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/me/bootstrap",
            json=_bootstrap_payload(rsa_pub=bad_key),
            headers=_auth_header(),
        )

    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_rsa_key"


@pytest.mark.asyncio
async def test_bootstrap_invalid_salt_size() -> None:
    """POST /v1/me/bootstrap avec un salt != 16 bytes retourne 400."""
    conn = _make_conn_mock()
    pool = _make_pool_with_conn(conn)

    bad_salt = base64.b64encode(b"too_short").decode()

    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/me/bootstrap",
            json=_bootstrap_payload(salt=bad_salt),
            headers=_auth_header(),
        )

    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_salt_size"


@pytest.mark.asyncio
async def test_bootstrap_already_done() -> None:
    """POST /v1/me/bootstrap lève 409 si l'user existe déjà avec is_system=False
    (vrai user déjà bootstrappé). Cf. flow `bootstrap_user`:
        1. get_id_by_keycloak_sub  → UUID existant
        2. _is_system_row          → False (vrai user)
        → raise 409 already_bootstrapped
    """
    from uuid import uuid4

    existing_id = uuid4()
    conn = _make_conn_mock()
    # fetchval enchaîne deux SELECTs : d'abord l'id, puis is_system.
    conn.fetchval = AsyncMock(side_effect=[existing_id, False])
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/me/bootstrap",
            json=_bootstrap_payload(),
            headers=_auth_header(),
        )

    assert r.status_code == 409
    body = r.json()
    assert body["detail"]["error"] == "already_bootstrapped"


# ─── Tests GET /v1/me/crypto ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_crypto_returns_blobs() -> None:
    """GET /v1/me/crypto retourne 200 avec les blobs et met à jour last_unlock_at."""
    conn = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value=_fake_record())
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.get("/v1/me/crypto", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert "salt_passphrase" in body
    assert "encrypted_rsa_private_key" in body
    assert "kdf_params" in body
    # Vérifie que touch_last_unlock a été appelé (via execute)
    conn.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_crypto_when_not_bootstrapped() -> None:
    """GET /v1/me/crypto retourne 404 si non bootstrappé."""
    conn = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value=None)
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.get("/v1/me/crypto", headers=_auth_header())

    assert r.status_code == 404


# ─── Tests PUT /v1/me/passphrase ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passphrase_change_updates_blobs() -> None:
    """PUT /v1/me/passphrase retourne 200 avec updated_at."""
    conn = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value=_fake_record())
    conn.fetchval = AsyncMock(return_value=_NOW)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool_with_conn(conn)

    payload = {
        "new_salt_passphrase": _salt_b64(),
        "new_encrypted_rsa_private_key": _blob_b64(),
        "new_encrypted_sym_key_by_pass": _blob_b64(),
        "kdf_memory_kb": 65536,
        "kdf_iterations": 3,
        "kdf_parallelism": 4,
    }

    async with _make_client(pool) as client:
        r = await client.put("/v1/me/passphrase", json=payload, headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert "updated_at" in body


# ─── Tests PUT /v1/me/recovery ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recovery_renew_updates_blob() -> None:
    """PUT /v1/me/recovery retourne 200 avec updated_at."""
    conn = _make_conn_mock()
    conn.fetchrow = AsyncMock(return_value=_fake_record())
    conn.fetchval = AsyncMock(return_value=_NOW)
    conn.execute = AsyncMock(return_value=None)
    pool = _make_pool_with_conn(conn)

    payload = {
        "new_salt_recovery": _salt_b64(),
        "new_encrypted_sym_key_by_recovery": _blob_b64(),
    }

    async with _make_client(pool) as client:
        r = await client.put("/v1/me/recovery", json=payload, headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert "updated_at" in body


# ─── Tests audit_log ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_created_on_bootstrap() -> None:
    """POST /v1/me/bootstrap insère une ligne d'audit_log."""
    conn = _make_conn_mock()
    conn.fetchval = AsyncMock(return_value=_USER_ID)

    execute_calls: list[str] = []

    async def capture_execute(query: str, *args: Any) -> None:
        execute_calls.append(query)

    conn.execute = capture_execute
    pool = _make_pool_with_conn(conn)

    async with _make_client(pool) as client:
        r = await client.post(
            "/v1/me/bootstrap",
            json=_bootstrap_payload(),
            headers=_auth_header(),
        )

    assert r.status_code == 201
    # Vérifie qu'au moins un INSERT dans audit_log a été exécuté
    audit_inserts = [q for q in execute_calls if "audit_log" in q]
    assert len(audit_inserts) >= 1
