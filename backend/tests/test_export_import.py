"""Tests export/import structure wallet — LOT_07."""
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

from app.models.api.exports import WalletExport, WalletImportRequest
from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Constantes ───────────────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NEW_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_SECRET_ID_1 = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_SECRET_ID_2 = uuid.UUID("cccccccc-0000-0000-0000-000000000002")
_SECRET_ID_3 = uuid.UUID("cccccccc-0000-0000-0000-000000000003")

_ENC_KEY_B64 = base64.b64encode(b"fake_encrypted_wallet_key_32bytes").decode()
_RANDOM_DESCRIPTOR = {"type": "random", "length": 32, "charset": "alphanum"}


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


# ─── Helpers ──────────────────────────────────────────────────────────────────


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


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
            "description": "A wallet",
            "owner_user_id": owner_user_id,
            "created_at": _NOW,
            "updated_at": _NOW,
            "my_permissions": permissions,
            "valued_secrets_count": 0,
            "placeholder_secrets_count": 2,
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


def _export_secret_row(
    name: str,
    *,
    secret_id: uuid.UUID | None = None,
    descriptor: dict[str, Any] | None = None,
    linked_secret_name: str | None = None,
    is_placeholder: bool = True,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": secret_id or uuid.uuid4(),
            "name": name,
            "description": None,
            "is_placeholder": is_placeholder,
            "generation_descriptor": descriptor,
            "generation_version": 1,
            "linked_secret_name": linked_secret_name,
        }
    )


def _wallet_export_row() -> FakeRecord:
    return FakeRecord({"id": _WALLET_ID, "name": "My Wallet", "description": "A wallet"})


# ─── Tests — Export ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_returns_versioned_structure() -> None:
    """GET /v1/wallets/{id}/export → format_version="1" présent."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if "wallet_grants" in query:
            return _fake_wallet_row()
        return _wallet_export_row()

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        if "wallet_tags" in query and "wallet_id" in query:
            return []
        if "secrets" in query and "wallet_id" in query:
            return []
        if "secret_tags" in query:
            return []
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/export", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert body["format_version"] == "1"
    assert "wallet" in body
    assert "secrets" in body


@pytest.mark.asyncio
async def test_export_no_values_in_payload() -> None:
    """GET export → encrypted_value et encrypted_wallet_key absents du payload."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if "wallet_grants" in query:
            return _fake_wallet_row()
        return _wallet_export_row()

    def _is_secrets_query(q: str) -> bool:
        return "secrets s" in q or (
            "secrets" in q and "wallet_id" in q and "LEFT JOIN" in q
        )

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        if _is_secrets_query(query):
            return [_export_secret_row("API_KEY", descriptor=_RANDOM_DESCRIPTOR)]
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/export", headers=_auth_header())

    assert r.status_code == 200
    raw_text = r.text
    assert "encrypted_value" not in raw_text
    assert "encrypted_wallet_key" not in raw_text


@pytest.mark.asyncio
async def test_export_includes_placeholders() -> None:
    """GET export → les placeholders sont inclus avec is_placeholder=true et leur descripteur."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if "wallet_grants" in query:
            return _fake_wallet_row()
        return _wallet_export_row()

    async def fetch_side(query: str, *args: Any) -> list[FakeRecord]:
        if "secrets s" in query and "LEFT JOIN" in query:
            return [
                _export_secret_row(
                    "API_KEY",
                    secret_id=_SECRET_ID_1,
                    descriptor=_RANDOM_DESCRIPTOR,
                    is_placeholder=True,
                )
            ]
        return []

    conn.fetchrow = fetchrow_side
    conn.fetch = fetch_side

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/export", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert len(body["secrets"]) == 1
    s = body["secrets"][0]
    assert s["name"] == "API_KEY"
    assert s["is_placeholder"] is True
    assert s["generation_descriptor"] == _RANDOM_DESCRIPTOR


@pytest.mark.asyncio
async def test_export_requires_read_permission() -> None:
    """GET export → 403 si caller n'a pas [read] (bit 0x01)."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # permissions=0 : aucune permission
        return _fake_wallet_row(permissions=0, owner_user_id=uuid.uuid4())

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/export", headers=_auth_header())

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "forbidden"


@pytest.mark.asyncio
async def test_export_filename_attachment() -> None:
    """GET export → header Content-Disposition avec nom du wallet."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if "wallet_grants" in query:
            return _fake_wallet_row(name="My Production Wallet")
        return FakeRecord({"id": _WALLET_ID, "name": "My Production Wallet", "description": None})

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/export", headers=_auth_header())

    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "vault-" in cd
    assert ".json" in cd


# ─── Tests — Import ───────────────────────────────────────────────────────────


def _import_payload(
    *,
    name: str = "Imported Wallet",
    secrets: list[dict[str, Any]] | None = None,
    format_version: str = "1",
) -> dict[str, Any]:
    return {
        "format_version": format_version,
        "wallet": {"name": name, "description": None, "tags": []},
        "secrets": secrets or [],
        "encrypted_wallet_key_for_owner": _ENC_KEY_B64,
    }


@pytest.mark.asyncio
async def test_import_creates_new_wallet() -> None:
    """POST /v1/wallets/import → 201 avec wallet_id."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())
    conn.fetchval = AsyncMock(return_value=_NEW_WALLET_ID)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(),
            headers=_auth_header(),
        )

    assert r.status_code == 201
    body = r.json()
    assert "wallet_id" in body
    assert body["secrets_created"] == 0
    assert body["skipped"] == []


@pytest.mark.asyncio
async def test_import_creates_secrets_in_correct_order() -> None:
    """POST import avec 2 secrets → secrets_created=2."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    fetchval_calls: list[Any] = [_NEW_WALLET_ID, _SECRET_ID_1, _SECRET_ID_2]
    call_n = 0

    async def fetchval_side(query: str, *args: Any) -> Any:
        nonlocal call_n
        val = fetchval_calls[min(call_n, len(fetchval_calls) - 1)]
        call_n += 1
        return val

    conn.fetchval = fetchval_side

    secrets = [
        {"name": "SECRET_A", "tags": [], "generation_descriptor": _RANDOM_DESCRIPTOR},
        {"name": "SECRET_B", "tags": [], "generation_descriptor": _RANDOM_DESCRIPTOR},
    ]

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(secrets=secrets),
            headers=_auth_header(),
        )

    assert r.status_code == 201
    body = r.json()
    assert body["secrets_created"] == 2


@pytest.mark.asyncio
async def test_import_resolves_linked_secret_by_name() -> None:
    """POST import avec linked_secret_name → execute appelé pour UPDATE linked_secret_id."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    fetchval_calls = [_NEW_WALLET_ID, _SECRET_ID_1, _SECRET_ID_2]
    call_n = 0

    async def fetchval_side(query: str, *args: Any) -> Any:
        nonlocal call_n
        val = fetchval_calls[min(call_n, len(fetchval_calls) - 1)]
        call_n += 1
        return val

    conn.fetchval = fetchval_side

    secrets = [
        {"name": "BASE_KEY", "tags": [], "generation_descriptor": _RANDOM_DESCRIPTOR},
        {
            "name": "DERIVED_KEY",
            "tags": [],
            "generation_descriptor": _RANDOM_DESCRIPTOR,
            "linked_secret_name": "BASE_KEY",
        },
    ]

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(secrets=secrets),
            headers=_auth_header(),
        )

    assert r.status_code == 201
    # Vérifie qu'un UPDATE a été appelé (résolution du linked_secret_id)
    execute_calls = [str(call) for call in conn.execute.await_args_list]
    update_calls = [c for c in execute_calls if "UPDATE" in c and "linked_secret_id" in c]
    assert len(update_calls) >= 1


@pytest.mark.asyncio
async def test_import_rejects_duplicate_secret_names_in_payload() -> None:
    """POST import avec doublons de noms → 422."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    secrets = [
        {"name": "DUPLICATE", "tags": [], "generation_descriptor": _RANDOM_DESCRIPTOR},
        {"name": "DUPLICATE", "tags": [], "generation_descriptor": _RANDOM_DESCRIPTOR},
    ]

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(secrets=secrets),
            headers=_auth_header(),
        )

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_import_validates_format_version() -> None:
    """POST import avec format_version="2" → 422."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(format_version="2"),
            headers=_auth_header(),
        )

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_import_normalizes_tags() -> None:
    """POST import avec tags en MAJUSCULES → normalisés en lowercase."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    fetchval_calls = [_NEW_WALLET_ID, _SECRET_ID_1]
    call_n = 0

    async def fetchval_side(query: str, *args: Any) -> Any:
        nonlocal call_n
        val = fetchval_calls[min(call_n, len(fetchval_calls) - 1)]
        call_n += 1
        return val

    conn.fetchval = fetchval_side

    payload = {
        "format_version": "1",
        "wallet": {"name": "Test", "description": None, "tags": ["PROD", "  STAGING  "]},
        "secrets": [
            {
                "name": "MY_KEY",
                "tags": ["DEV", "  API  "],
                "generation_descriptor": _RANDOM_DESCRIPTOR,
            }
        ],
        "encrypted_wallet_key_for_owner": _ENC_KEY_B64,
    }

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post("/v1/wallets/import", json=payload, headers=_auth_header())

    assert r.status_code == 201
    # Vérifie que executemany a été appelé avec des tags normalisés
    executemany_calls = conn.executemany.await_args_list
    tag_data: list[tuple[Any, ...]] = []
    for call in executemany_calls:
        args = call[0]
        if len(args) >= 2 and isinstance(args[1], list):
            tag_data.extend(args[1])

    inserted_tags = [str(row[1]) for row in tag_data if len(row) >= 2]
    for tag in inserted_tags:
        assert tag == tag.lower().strip(), f"Tag non normalisé: {tag!r}"


@pytest.mark.asyncio
async def test_import_atomic_rollback_on_failure() -> None:
    """POST import avec linked_secret_name invalide → 422, pas de wallet créé."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    secrets = [
        {
            "name": "MY_KEY",
            "tags": [],
            "generation_descriptor": _RANDOM_DESCRIPTOR,
            "linked_secret_name": "NON_EXISTENT",
        }
    ]

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(secrets=secrets),
            headers=_auth_header(),
        )

    # La validation Pydantic doit rejeter linked_secret_name invalide avant tout INSERT
    assert r.status_code == 422
    # Aucun fetchval pour INSERT wallet ne doit avoir été appelé
    conn.fetchval.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_then_import_roundtrip() -> None:
    """Roundtrip : WalletExport sérialisé → WalletImportRequest valide."""
    export = WalletExport(
        format_version="1",
        exported_at=_NOW,
        exported_from="https://vault.yoops.org",
        wallet={"name": "Roundtrip Wallet", "description": "Test", "tags": ["test"]},
        secrets=[
            {
                "name": "API_KEY",
                "description": None,
                "tags": ["api"],
                "is_placeholder": True,
                "generation_descriptor": _RANDOM_DESCRIPTOR,
                "generation_version": 1,
                "linked_secret_name": None,
            }
        ],
    )

    # Sérialise comme le ferait l'endpoint export
    payload = export.model_dump(mode="json")
    # Ajoute encrypted_wallet_key_for_owner (requis à l'import, absent à l'export)
    payload["encrypted_wallet_key_for_owner"] = _ENC_KEY_B64

    # Doit valider sans erreur
    req = WalletImportRequest.model_validate(payload)
    assert req.wallet.name == "Roundtrip Wallet"
    assert len(req.secrets) == 1
    assert req.secrets[0].name == "API_KEY"
    assert req.format_version == "1"


@pytest.mark.asyncio
async def test_audit_log_export() -> None:
    """GET export → audit_log INSERT appelé avec action wallet.exported_structure."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if "wallet_grants" in query:
            return _fake_wallet_row()
        return _wallet_export_row()

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/wallets/{_WALLET_ID}/export", headers=_auth_header())

    assert r.status_code == 200
    # Vérifie que execute a été appelé avec wallet.exported_structure
    execute_calls = [str(call) for call in conn.execute.await_args_list]
    audit_calls = [c for c in execute_calls if "wallet.exported_structure" in c]
    assert len(audit_calls) >= 1


@pytest.mark.asyncio
async def test_audit_log_import() -> None:
    """POST import → audit_log INSERT appelé avec action wallet.imported."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())
    conn.fetchval = AsyncMock(return_value=_NEW_WALLET_ID)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/wallets/import",
            json=_import_payload(),
            headers=_auth_header(),
        )

    assert r.status_code == 201
    execute_calls = [str(call) for call in conn.execute.await_args_list]
    audit_calls = [c for c in execute_calls if "wallet.imported" in c]
    assert len(audit_calls) >= 1


# ─── Tests — Modèles Pydantic directs ────────────────────────────────────────


def test_wallet_export_model_rejects_duplicate_names() -> None:
    """WalletExport lève ValueError si noms de secrets dupliqués."""
    with pytest.raises(ValidationError, match="Duplicate"):
        WalletExport(
            format_version="1",
            wallet={"name": "W"},
            secrets=[
                {"name": "X", "generation_descriptor": _RANDOM_DESCRIPTOR},
                {"name": "X", "generation_descriptor": _RANDOM_DESCRIPTOR},
            ],
        )


def test_wallet_export_model_rejects_invalid_linked_name() -> None:
    """WalletExport lève ValueError si linked_secret_name ne référence pas un secret connu."""
    with pytest.raises(ValidationError, match="linked_secret_name"):
        WalletExport(
            format_version="1",
            wallet={"name": "W"},
            secrets=[
                {
                    "name": "KEY",
                    "generation_descriptor": _RANDOM_DESCRIPTOR,
                    "linked_secret_name": "DOES_NOT_EXIST",
                }
            ],
        )


def test_wallet_import_request_rejects_wrong_format_version() -> None:
    """WalletImportRequest lève ValidationError si format_version != "1"."""
    with pytest.raises(ValidationError):
        WalletImportRequest.model_validate(
            {
                "format_version": "2",
                "wallet": {"name": "W"},
                "secrets": [],
                "encrypted_wallet_key_for_owner": _ENC_KEY_B64,
            }
        )


def test_wallet_import_request_normalizes_tags() -> None:
    """WalletImportRequest normalise les tags wallet et secrets en lowercase."""
    req = WalletImportRequest.model_validate(
        {
            "format_version": "1",
            "wallet": {"name": "W", "tags": ["PROD", "  API  "]},
            "secrets": [
                {
                    "name": "MY_KEY",
                    "tags": ["DEV", "  STAGING  "],
                    "generation_descriptor": _RANDOM_DESCRIPTOR,
                }
            ],
            "encrypted_wallet_key_for_owner": _ENC_KEY_B64,
        }
    )
    assert req.wallet.tags == ["prod", "api"]
    assert req.secrets[0].tags == ["dev", "staging"]
