"""Tests des endpoints placeholder + descripteurs de génération — LOT_06."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.models.api.generators import (
    BcryptPasswordDescriptor,
    BytesDescriptor,
    RandomDescriptor,
    RsaKeypairDescriptor,
    SshKeypairDescriptor,
    TemplateDescriptor,
    TlsCertificateDescriptor,
    UuidDescriptor,
)
from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Constantes ───────────────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000010")
_SECRET_ID_2 = uuid.UUID("dddddddd-0000-0000-0000-000000000011")

_PERM_ALL = 63
_PERM_READ_ONLY = 0x01       # 0x01 — [read] seulement
_PERM_ADD_ONLY = 0x02        # 0x02 — [add] seulement
_PERM_INIT_ONLY = 0x04       # 0x04 — [init] seulement
_PERM_NO_INIT = _PERM_ALL & ~0x04  # Tout sauf [init]

_FAKE_ENC_VALUE = base64.b64encode(b"fake_encrypted_secret_value").decode()
_RANDOM_DESCRIPTOR = {"type": "random", "length": 32, "charset": "alphanum"}

# ─── Fixtures ─────────────────────────────────────────────────────────────────


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


# ─── FakeRecord + helpers ─────────────────────────────────────────────────────


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


def _fake_user_row(user_id: uuid.UUID = _CALLER_ID) -> FakeRecord:
    return FakeRecord(
        {
            "id": user_id,
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


def _fake_wallet_row(*, permissions: int = _PERM_ALL) -> FakeRecord:
    return FakeRecord(
        {
            "id": _WALLET_ID,
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


def _fake_placeholder_row(
    *,
    secret_id: uuid.UUID = _SECRET_ID,
    name: str = "DB_PASSWORD",
    descriptor: dict[str, Any] | None = None,
    generation_version: int = 1,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": secret_id,
            "wallet_id": _WALLET_ID,
            "name": name,
            "description": None,
            "encrypted_value": None,
            "is_placeholder": True,
            "generation_version": generation_version,
            "linked_secret_id": None,
            "generation_descriptor": descriptor or _RANDOM_DESCRIPTOR,
            "created_at": _NOW,
            "updated_at": _NOW,
            "created_by_user_id": _CALLER_ID,
            "created_by_api_key_id": None,
            "updated_by_user_id": None,
            "updated_by_api_key_id": None,
        }
    )


def _fake_valued_row(
    *,
    secret_id: uuid.UUID = _SECRET_ID,
    name: str = "DB_PASSWORD",
    generation_version: int = 2,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": secret_id,
            "wallet_id": _WALLET_ID,
            "name": name,
            "description": None,
            "encrypted_value": b"fake_encrypted_value",
            "is_placeholder": False,
            "generation_version": generation_version,
            "linked_secret_id": None,
            "generation_descriptor": None,
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


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de validation des descripteurs (Pydantic seul — pas d'I/O)
# ═══════════════════════════════════════════════════════════════════════════════


def test_descriptor_random_validates_charset_named() -> None:
    """Type random accepte les charsets nommés."""
    for cs in ("alphanum", "alpha", "numeric", "hex", "base64url", "printable_ascii"):
        d = RandomDescriptor(type="random", length=16, charset=cs)
        assert d.charset == cs


def test_descriptor_random_validates_charset_custom() -> None:
    """Type random accepte un charset custom printable ASCII ≥ 4 chars."""
    d = RandomDescriptor(type="random", length=16, charset="!@#$%")
    assert d.charset == "!@#$%"


def test_descriptor_random_rejects_short_custom_charset() -> None:
    """Type random rejette un charset custom < 4 caractères."""
    with pytest.raises(ValidationError):
        RandomDescriptor(type="random", length=16, charset="ab!")


def test_descriptor_random_rejects_non_printable_charset() -> None:
    """Type random rejette un charset contenant des caractères non-ASCII."""
    with pytest.raises(ValidationError):
        RandomDescriptor(type="random", length=16, charset="abc\x00")


def test_descriptor_random_rejects_length_below_min() -> None:
    """Type random : length < 8 → erreur."""
    with pytest.raises(ValidationError):
        RandomDescriptor(type="random", length=7, charset="alphanum")


def test_descriptor_uuid_v4_only() -> None:
    """Type uuid accepte v4 et v7, rejette v1."""
    d4 = UuidDescriptor(type="uuid", version=4)
    assert d4.version == 4
    d7 = UuidDescriptor(type="uuid", version=7)
    assert d7.version == 7
    with pytest.raises(ValidationError):
        UuidDescriptor.model_validate({"type": "uuid", "version": 1})


def test_descriptor_bytes_encoding_validation() -> None:
    """Type bytes : encoding doit être 'base64url' ou 'hex'."""
    d = BytesDescriptor(type="bytes", length=32, encoding="hex")
    assert d.encoding == "hex"
    with pytest.raises(ValidationError):
        BytesDescriptor.model_validate({"type": "bytes", "length": 32, "encoding": "base64"})


def test_descriptor_bytes_length_bounds() -> None:
    """Type bytes : length entre 1 et 4096."""
    BytesDescriptor(type="bytes", length=1, encoding="hex")
    BytesDescriptor(type="bytes", length=4096, encoding="hex")
    with pytest.raises(ValidationError):
        BytesDescriptor(type="bytes", length=0, encoding="hex")
    with pytest.raises(ValidationError):
        BytesDescriptor(type="bytes", length=4097, encoding="hex")


def test_descriptor_template_with_variables() -> None:
    """Type template avec variables littérales et sous-descripteurs."""
    d = TemplateDescriptor(
        type="template",
        template="postgresql://{user}:{password}@{host}:5432/{db}",
        variables={
            "user": {"literal": "agflow"},
            "password": {"type": "random", "length": 32, "charset": "alphanum"},
            "host": {"literal": "postgres.lan"},
            "db": {"literal": "mydb"},
        },
    )
    assert d.template.startswith("postgresql://")


def test_descriptor_template_missing_variable_rejected() -> None:
    """Type template : placeholder dans template sans variable → erreur."""
    with pytest.raises(ValidationError):
        TemplateDescriptor(
            type="template",
            template="{user}:{password}",
            variables={"user": {"literal": "admin"}},
            # "password" manquant
        )


def test_descriptor_rsa_key_size_must_be_2048_or_4096() -> None:
    """Type rsa_keypair : key_size ∈ {2048, 3072, 4096}."""
    RsaKeypairDescriptor(type="rsa_keypair", key_size=2048, format="pem")
    RsaKeypairDescriptor(type="rsa_keypair", key_size=3072, format="pem")
    RsaKeypairDescriptor(type="rsa_keypair", key_size=4096, format="pem")
    with pytest.raises(ValidationError):
        RsaKeypairDescriptor.model_validate(
            {"type": "rsa_keypair", "key_size": 1024, "format": "pem"}
        )


def test_descriptor_ssh_keypair_algorithms() -> None:
    """Type ssh_keypair : algorithm ∈ {ed25519, rsa}."""
    SshKeypairDescriptor(type="ssh_keypair", algorithm="ed25519")
    SshKeypairDescriptor(type="ssh_keypair", algorithm="rsa")
    with pytest.raises(ValidationError):
        SshKeypairDescriptor.model_validate({"type": "ssh_keypair", "algorithm": "ecdsa"})


def test_descriptor_tls_certificate_self_signed_only() -> None:
    """Type tls_certificate : self_signed doit être True."""
    d = TlsCertificateDescriptor(
        type="tls_certificate",
        common_name="agent.lan",
        subject_alt_names=["agent.lan"],
        validity_days=365,
        key_size=2048,
        self_signed=True,
    )
    assert d.self_signed is True
    with pytest.raises(ValidationError):
        TlsCertificateDescriptor.model_validate({
            "type": "tls_certificate",
            "common_name": "agent.lan",
            "validity_days": 365,
            "key_size": 2048,
            "self_signed": False,
        })


def test_descriptor_tls_certificate_empty_common_name_rejected() -> None:
    """Type tls_certificate : common_name vide → erreur."""
    with pytest.raises(ValidationError):
        TlsCertificateDescriptor(
            type="tls_certificate",
            common_name="   ",
            validity_days=365,
            key_size=2048,
            self_signed=True,
        )


def test_descriptor_bcrypt_password_rounds_bounds() -> None:
    """Type bcrypt_password : rounds entre 10 et 14."""
    BcryptPasswordDescriptor(type="bcrypt_password", length=24, rounds=10)
    BcryptPasswordDescriptor(type="bcrypt_password", length=24, rounds=14)
    with pytest.raises(ValidationError):
        BcryptPasswordDescriptor(type="bcrypt_password", length=24, rounds=9)
    with pytest.raises(ValidationError):
        BcryptPasswordDescriptor(type="bcrypt_password", length=24, rounds=15)


def test_descriptor_invalid_type_rejected() -> None:
    """Un type inconnu est rejeté par la discriminated union."""
    from pydantic import TypeAdapter, ValidationError

    from app.models.api.generators import GenerationDescriptor

    ta: TypeAdapter[GenerationDescriptor] = TypeAdapter(GenerationDescriptor)
    with pytest.raises(ValidationError):
        ta.validate_python({"type": "unknown_type", "length": 32})


# ═══════════════════════════════════════════════════════════════════════════════
# Tests des endpoints (avec mocks)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_placeholder_create_happy_path() -> None:
    """POST /secrets/placeholder → 201 avec secret_id."""
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
    conn.fetchval = AsyncMock(return_value=_SECRET_ID)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/placeholder",
            json={
                "name": "DB_PASSWORD",
                "generation_descriptor": _RANDOM_DESCRIPTOR,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text
    body = r.json()
    assert "secret_id" in body
    assert body["secret_id"] == str(_SECRET_ID)


@pytest.mark.asyncio
async def test_placeholder_create_invalid_descriptor_422() -> None:
    """POST /secrets/placeholder avec descripteur invalide → 422."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    conn.fetchrow = fetchrow_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/placeholder",
            json={
                "name": "DB_PASSWORD",
                "generation_descriptor": {"type": "random", "length": 3},  # length < 8
            },
            headers=_auth_header(),
        )

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_placeholder_requires_add_permission() -> None:
    """POST /secrets/placeholder → 403 si [add] manquant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_READ_ONLY)  # pas de [add]

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/placeholder",
            json={
                "name": "DB_PASSWORD",
                "generation_descriptor": _RANDOM_DESCRIPTOR,
            },
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"


@pytest.mark.asyncio
async def test_populate_happy_path() -> None:
    """POST /secrets/{name}/populate → 200 avec generation_version."""
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
            return _fake_placeholder_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side
    conn.fetchval = AsyncMock(return_value=2)  # new generation_version

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD/populate",
            json={"encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json()["generation_version"] == 2


@pytest.mark.asyncio
async def test_populate_requires_init_permission() -> None:
    """POST /secrets/{name}/populate → 403 si [init] manquant."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_NO_INIT)  # pas de [init]

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD/populate",
            json={"encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"


@pytest.mark.asyncio
async def test_populate_already_populated() -> None:
    """POST /secrets/{name}/populate sur un secret valorisé → 409."""
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
            return _fake_valued_row()  # is_placeholder=False
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD/populate",
            json={"encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "secret_already_populated"


@pytest.mark.asyncio
async def test_put_on_placeholder_rejects() -> None:
    """PUT sur un placeholder → 409 placeholder_expected."""
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
            return _fake_placeholder_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD",
            json={"encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "placeholder_expected"


@pytest.mark.asyncio
async def test_get_placeholder_returns_424_with_descriptor() -> None:
    """GET /secrets/{name} sur placeholder → 424 avec descripteur dans details."""
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
            return _fake_placeholder_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD",
            headers=_auth_header(),
        )

    assert r.status_code == 424, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "placeholder_value_missing"
    assert detail["details"]["is_placeholder"] is True
    assert detail["details"]["generation_descriptor"]["type"] == "random"


@pytest.mark.asyncio
async def test_get_descriptor_on_placeholder_returns_200() -> None:
    """GET /secrets/{name}/descriptor → 200 avec descripteur."""
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
            return _fake_placeholder_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD/descriptor",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_placeholder"] is True
    assert body["generation_descriptor"]["type"] == "random"
    assert body["name"] == "DB_PASSWORD"


@pytest.mark.asyncio
async def test_get_descriptor_on_valued_secret_returns_404() -> None:
    """GET /secrets/{name}/descriptor sur secret valorisé → 404."""
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
            return _fake_valued_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD/descriptor",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_placeholder"


@pytest.mark.asyncio
async def test_descriptor_accessible_with_init_permission_only() -> None:
    """GET /descriptor accessible avec [init] seul (sans [read])."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_INIT_ONLY)
        if call_n == 3:
            return _fake_placeholder_row()
        return None

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/DB_PASSWORD/descriptor",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_linked_secret_in_same_wallet_ok() -> None:
    """POST placeholder avec linked_secret_id du même wallet → 201."""
    conn = _make_conn()
    call_n = 0
    fetchval_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def fetchval_side(query: str, *args: Any) -> Any:
        nonlocal fetchval_n
        fetchval_n += 1
        if fetchval_n == 1:
            # linked_secret_id wallet lookup → même wallet
            return _WALLET_ID
        # INSERT RETURNING id
        return _SECRET_ID

    conn.fetchrow = fetchrow_side
    conn.fetchval = fetchval_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/placeholder",
            json={
                "name": "DB_PASSWORD_HASH",
                "generation_descriptor": _RANDOM_DESCRIPTOR,
                "linked_secret_id": str(_SECRET_ID_2),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_linked_secret_cross_wallet_rejected() -> None:
    """POST placeholder avec linked_secret_id d'un autre wallet → 400."""
    other_wallet = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
    conn = _make_conn()
    call_n = 0
    fetchval_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_ALL)

    async def fetchval_side(query: str, *args: Any) -> Any:
        nonlocal fetchval_n
        fetchval_n += 1
        if fetchval_n == 1:
            # linked_secret_id appartient à un autre wallet
            return other_wallet
        return _SECRET_ID

    conn.fetchrow = fetchrow_side
    conn.fetchval = fetchval_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/placeholder",
            json={
                "name": "DB_PASSWORD_HASH",
                "generation_descriptor": _RANDOM_DESCRIPTOR,
                "linked_secret_id": str(_SECRET_ID_2),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "linked_secret_must_be_in_same_wallet"


@pytest.mark.asyncio
async def test_wallet_counters_reflect_placeholder_and_valued() -> None:
    """GET /wallets expose valued_secrets_count et placeholder_secrets_count corrects."""
    conn = _make_conn()
    call_n = 0
    fetch_n = 0

    wallet_row = FakeRecord(
        {
            "id": _WALLET_ID,
            "name": "Test Wallet",
            "description": None,
            "owner_user_id": _CALLER_ID,
            "created_at": _NOW,
            "updated_at": _NOW,
            "my_permissions": _PERM_ALL,
            "valued_secrets_count": 3,
            "placeholder_secrets_count": 2,
            "deleted_at": None,
        }
    )

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return None  # la liste utilise fetch()

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        nonlocal fetch_n
        fetch_n += 1
        if fetch_n == 1:
            return [wallet_row]
        return []  # tags

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/wallets", headers=_auth_header())

    assert r.status_code == 200, r.text
    wallets = r.json()["wallets"]
    assert len(wallets) == 1
    assert wallets[0]["valued_secrets_count"] == 3
    assert wallets[0]["placeholder_secrets_count"] == 2


@pytest.mark.asyncio
async def test_audit_metadata_includes_generator_type() -> None:
    """Audit log de secret.placeholder_created inclut generator_type."""
    import json

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
        if "INSERT INTO audit_log" in query and len(args) > 8 and args[8] is not None:
            audit_metadata = json.loads(args[8])

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=_SECRET_ID)
    conn.execute = execute_side

    async with _make_client(_make_pool(conn)) as client:
        await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets/placeholder",
            json={
                "name": "DB_PASSWORD",
                "generation_descriptor": _RANDOM_DESCRIPTOR,
            },
            headers=_auth_header(),
        )

    assert audit_metadata is not None, "Audit log non appelé"
    assert "generator_type" in audit_metadata
    assert audit_metadata["generator_type"] == "random"
    assert audit_metadata["secret_name"] == "DB_PASSWORD"
