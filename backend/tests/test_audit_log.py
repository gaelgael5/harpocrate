"""Tests LOT_10 — API consultation audit_log + purge job."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Constantes ───────────────────────────────────────────────────────────────

_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER2_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_WALLET2_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_SECRET_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_API_KEY_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_HMAC_KEY_BYTES = b"k" * 32
_HMAC_KEY_B64 = base64.b64encode(_HMAC_KEY_BYTES).decode()

_NOW = datetime.datetime(2026, 5, 1, 12, 0, 0, tzinfo=datetime.UTC)


# ─── Fixtures d'environnement ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", _HMAC_KEY_B64)
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security

    sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(backup)


# ─── FakeRecord ───────────────────────────────────────────────────────────────


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


# ─── Helpers pool/conn ────────────────────────────────────────────────────────


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
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

    pool_mod._pool = pool  # type: ignore[assignment,unused-ignore]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── Helpers data ─────────────────────────────────────────────────────────────


def _fake_user_row(user_id: uuid.UUID = _USER_ID) -> FakeRecord:
    return FakeRecord(
        id=user_id,
        keycloak_sub="test-sub-001",
        email="alice@example.com",
        display_name="Alice",
        rsa_public_key=b"\x00" * 32,
        salt_passphrase=b"\x00" * 32,
        salt_recovery=b"\x00" * 32,
        encrypted_rsa_private_key=b"\x00" * 32,
        encrypted_sym_key_by_pass=b"\x00" * 32,
        encrypted_sym_key_by_recovery=b"\x00" * 32,
        kdf_memory_kb=65536,
        kdf_iterations=3,
        kdf_parallelism=4,
        rsa_key_size=2048,
        created_at=_NOW,
        updated_at=_NOW,
        last_unlock_at=None,
    )


def _fake_audit_row(
    row_id: int = 1,
    action: str = "secret.read",
    actor_user_id: uuid.UUID | None = _USER_ID,
    actor_api_key_id: uuid.UUID | None = None,
    target_wallet_id: uuid.UUID | None = _WALLET_ID,
    target_secret_id: uuid.UUID | None = _SECRET_ID,
    metadata: dict[str, Any] | None = None,
    success: bool = True,
) -> FakeRecord:
    return FakeRecord(
        id=row_id,
        occurred_at=_NOW,
        action=action,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
        actor_ip="10.0.0.1",
        target_wallet_id=target_wallet_id,
        target_secret_id=target_secret_id,
        target_user_id=None,
        target_api_key_id=None,
        metadata=metadata,
        success=success,
        error_code=None,
        actor_user_email="alice@example.com",
        actor_user_display_name="Alice",
        actor_api_key_name=None,
        target_wallet_name="My Wallet",
    )


def _api_key_audit_row(
    row_id: int = 1,
    action: str = "secret.read",
    api_key_id: uuid.UUID = _API_KEY_ID,
) -> FakeRecord:
    return FakeRecord(
        id=row_id,
        occurred_at=_NOW,
        action=action,
        actor_user_id=None,
        actor_api_key_id=api_key_id,
        actor_ip="10.0.0.2",
        target_wallet_id=_WALLET_ID,
        target_secret_id=_SECRET_ID,
        target_user_id=None,
        target_api_key_id=None,
        metadata=None,
        success=True,
        error_code=None,
        actor_user_email=None,
        actor_user_display_name=None,
        actor_api_key_name="agent-prod",
        target_wallet_name="My Wallet",
    )


def _make_api_key_token(
    api_key_id: uuid.UUID = _API_KEY_ID,
    perms: int = 0x3F,
) -> str:
    from app.core.api_key_token import encode_token

    auth_b64 = base64.urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode()
    dkey_b64 = base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode()
    return encode_token(
        api_key_id=api_key_id,
        exp=0,
        perms=perms,
        auth_secret_b64=auth_b64,
        dkey_b64=dkey_b64,
        master_key_b64=_HMAC_KEY_B64,
    )


def _jwt_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token(sub='test-sub-001')}"}


# ─── Conn setup helpers ────────────────────────────────────────────────────────


def _setup_jwt_conn(
    conn: MagicMock,
    audit_rows: list[FakeRecord],
    owned_wallet_ids: list[uuid.UUID] | None = None,
) -> None:
    """Configure conn pour un caller JWT typique."""
    if owned_wallet_ids is None:
        owned_wallet_ids = []

    # fetchrow → user (get_by_keycloak_sub dans la dep)
    conn.fetchrow = AsyncMock(return_value=_fake_user_row())

    # fetch side effects :
    # 1. get_owned_wallet_ids → owned wallet rows
    # 2. query_audit_log → audit rows
    owned_rows = [FakeRecord(id=wid) for wid in owned_wallet_ids]

    call_count = 0

    async def _fetch_side_effect(*args: Any, **kwargs: Any) -> list[FakeRecord]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return owned_rows
        return audit_rows

    conn.fetch = _fetch_side_effect


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — JWT: voit ses propres actions
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditLogJwtOwn:
    @pytest.mark.asyncio
    async def test_audit_log_jwt_sees_own_actions(self) -> None:
        """Un JWT voit ses propres actions dans audit_log."""
        conn = _make_conn()
        fake_rows = [_fake_audit_row(actor_user_id=_USER_ID)]
        _setup_jwt_conn(conn, fake_rows)

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log", headers=_jwt_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert len(data["events"]) == 1
        assert data["events"][0]["action"] == "secret.read"

    @pytest.mark.asyncio
    async def test_audit_log_jwt_sees_actions_on_owned_wallets(self) -> None:
        """Un JWT voit les actions d'autres acteurs sur ses wallets owned."""
        conn = _make_conn()
        # Simule un event d'un autre user sur le wallet de alice
        other_user_row = _fake_audit_row(
            actor_user_id=_USER2_ID, target_wallet_id=_WALLET_ID
        )
        _setup_jwt_conn(conn, [other_user_row], owned_wallet_ids=[_WALLET_ID])

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log", headers=_jwt_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["actor"]["id"] == str(_USER2_ID)

    @pytest.mark.asyncio
    async def test_audit_log_jwt_combines_or_filter(self) -> None:
        """Le filtre OR (own_actions OR owned_wallets) interroge bien get_owned_wallet_ids."""
        conn = _make_conn()
        _setup_jwt_conn(conn, [], owned_wallet_ids=[_WALLET_ID, _WALLET2_ID])

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log", headers=_jwt_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert data["events"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — API key: filtre forcé
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditLogApiKey:
    def _api_key_headers(self) -> dict[str, str]:
        token = _make_api_key_token()
        return {"Authorization": f"Bearer {token}"}

    def _setup_api_key_conn(
        self,
        conn: MagicMock,
        audit_rows: list[FakeRecord],
    ) -> None:
        """Configure conn pour un caller API key (validate_api_key_token doit être mocké)."""
        conn.fetch = AsyncMock(return_value=audit_rows)

    def _mock_api_key_validation(self) -> Any:
        from app.core.api_key_auth import ApiKeyCaller

        caller = ApiKeyCaller(
            api_key_id=_API_KEY_ID,
            owner_user_id=_USER_ID,
            wallet_id=_WALLET_ID,
            permissions=0x3F,
            decryption_key_b64=base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode(),
        )
        return patch(
            "app.api.v1.audit_log.validate_api_key_token",
            new=AsyncMock(return_value=caller),
        )

    @pytest.mark.asyncio
    async def test_audit_log_api_key_sees_only_own_actions(self) -> None:
        """Une API key ne voit que ses propres actions."""
        conn = _make_conn()
        self._setup_api_key_conn(conn, [_api_key_audit_row()])

        with self._mock_api_key_validation():
            async with _make_client(_make_pool(conn)) as client:
                resp = await client.get(
                    "/v1/audit-log", headers=self._api_key_headers()
                )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["actor"]["type"] == "api_key"
        assert data["events"][0]["actor"]["id"] == str(_API_KEY_ID)

    @pytest.mark.asyncio
    async def test_audit_log_api_key_filters_forced(self) -> None:
        """Même si l'API key passe wallet_id= en query, elle ne voit que ses propres actions.

        La preuve : les rows retournées correspondent à l'api_key, pas au wallet passé.
        """
        conn = _make_conn()
        # La DB retourne uniquement les actions de l'API key
        # (le repo applique force_actor_api_key_id — wallet_id= est ignoré)
        self._setup_api_key_conn(conn, [])

        with self._mock_api_key_validation():
            async with _make_client(_make_pool(conn)) as client:
                # Passe wallet_id d'un autre wallet — doit être ignoré
                resp = await client.get(
                    f"/v1/audit-log?wallet_id={_WALLET2_ID}",
                    headers=self._api_key_headers(),
                )

        assert resp.status_code == 200
        # Aucun event visible (les events de cet api_key_id sont vides)
        data = resp.json()
        assert data["events"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — Pagination cursor
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditLogPagination:
    @pytest.mark.asyncio
    async def test_audit_log_pagination_cursor(self) -> None:
        """next_cursor est retourné quand il y a plus d'éléments que limit."""
        conn = _make_conn()
        # limit=2, on retourne 3 rows (limit+1) → has_more=True
        rows = [
            _fake_audit_row(row_id=3),
            _fake_audit_row(row_id=2),
            _fake_audit_row(row_id=1),  # +1 pour détecter has_more
        ]
        _setup_jwt_conn(conn, rows)

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log?limit=2", headers=_jwt_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2
        assert data["next_cursor"] is not None

    @pytest.mark.asyncio
    async def test_audit_log_pagination_no_next_cursor_when_exhausted(self) -> None:
        """next_cursor est null quand on reçoit exactement limit rows ou moins."""
        conn = _make_conn()
        rows = [_fake_audit_row(row_id=1)]
        _setup_jwt_conn(conn, rows)

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log?limit=50", headers=_jwt_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["next_cursor"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — Filtres transmis au service
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditLogFilters:
    @pytest.mark.asyncio
    async def test_audit_log_action_prefix_filter(self) -> None:
        """Le filtre action_prefix est transmis et retourne les events correspondants."""
        conn = _make_conn()
        rows = [_fake_audit_row(action="secret.read"), _fake_audit_row(action="secret.created")]
        _setup_jwt_conn(conn, rows)

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get(
                "/v1/audit-log?action_prefix=secret.", headers=_jwt_headers()
            )

        assert resp.status_code == 200
        data = resp.json()
        # Les rows sont retournées (le filtrage est fait par la DB, ici mockée)
        assert len(data["events"]) == 2

    @pytest.mark.asyncio
    async def test_audit_log_date_range_filter(self) -> None:
        """Les filtres since/until sont acceptés (400 si malformés)."""
        conn = _make_conn()
        _setup_jwt_conn(conn, [])

        async with _make_client(_make_pool(conn)) as client:
            # Dates ISO 8601 valides
            resp = await client.get(
                "/v1/audit-log?since=2026-01-01T00:00:00Z&until=2026-12-31T23:59:59Z",
                headers=_jwt_headers(),
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_log_success_filter(self) -> None:
        """Le filtre success=false est accepté et transmis."""
        conn = _make_conn()
        failed_row = _fake_audit_row(success=False)
        _setup_jwt_conn(conn, [failed_row])

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get(
                "/v1/audit-log?success=false", headers=_jwt_headers()
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["events"][0]["success"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — Endpoint /actions
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditLogActionsEndpoint:
    @pytest.mark.asyncio
    async def test_audit_log_actions_endpoint_lists_distinct(self) -> None:
        """GET /v1/audit-log/actions retourne la liste des actions distinctes."""
        conn = _make_conn()
        # JWT auth : get_by_keycloak_sub
        conn.fetchrow = AsyncMock(return_value=_fake_user_row())
        # get_distinct_actions → fetch
        distinct_rows = [
            FakeRecord(action="api_key.created"),
            FakeRecord(action="secret.read"),
            FakeRecord(action="wallet.created"),
        ]
        conn.fetch = AsyncMock(return_value=distinct_rows)

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log/actions", headers=_jwt_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert "api_key.created" in data["actions"]
        assert "secret.read" in data["actions"]
        assert "wallet.created" in data["actions"]

    @pytest.mark.asyncio
    async def test_audit_log_actions_requires_auth(self) -> None:
        """GET /v1/audit-log/actions sans auth retourne 401."""
        conn = _make_conn()

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log/actions")

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_audit_log_requires_auth(self) -> None:
        """GET /v1/audit-log sans auth retourne 401."""
        conn = _make_conn()

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get("/v1/audit-log")

        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — Metadata sanitization (unit tests, pas d'HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetadataSanitization:
    def test_strip_sensitive_metadata_removes_known_keys(self) -> None:
        """Les clés sensibles sont remplacées par [REDACTED]."""
        from app.db.repositories.audit_log import strip_sensitive_metadata

        raw: dict[str, Any] = {
            "secret_name": "ANTHROPIC_API_KEY",
            "passphrase": "super-secret",
            "encrypted_value": b"\xde\xad",
            "token": "should-be-redacted",
        }
        result = strip_sensitive_metadata(raw)
        assert result is not None
        assert result["secret_name"] == "ANTHROPIC_API_KEY"
        assert result["passphrase"] == "[REDACTED]"
        assert result["encrypted_value"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"

    def test_strip_sensitive_metadata_none_input(self) -> None:
        """None retourne None."""
        from app.db.repositories.audit_log import strip_sensitive_metadata

        assert strip_sensitive_metadata(None) is None

    def test_strip_sensitive_metadata_clean_input(self) -> None:
        """Une metadata sans clés sensibles est retournée intacte."""
        from app.db.repositories.audit_log import strip_sensitive_metadata

        raw: dict[str, Any] = {"secret_name": "MY_KEY", "is_placeholder": True}
        result = strip_sensitive_metadata(raw)
        assert result == raw


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — Cursor encode/decode
# ═══════════════════════════════════════════════════════════════════════════════


class TestCursor:
    def test_encode_decode_roundtrip(self) -> None:
        """encode_cursor / decode_cursor sont inverses l'un de l'autre."""
        from app.db.repositories.audit_log import decode_cursor, encode_cursor

        dt = datetime.datetime(2026, 5, 1, 10, 0, 0, tzinfo=datetime.UTC)
        row_id = 42_000

        encoded = encode_cursor(dt, row_id)
        decoded_dt, decoded_id = decode_cursor(encoded)

        assert decoded_id == row_id
        assert decoded_dt == dt

    def test_decode_invalid_cursor_raises(self) -> None:
        """Un cursor invalide lève ValueError."""
        from app.db.repositories.audit_log import decode_cursor

        with pytest.raises(ValueError):
            decode_cursor("not-a-valid-cursor!!!")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — Purge job
# ═══════════════════════════════════════════════════════════════════════════════


class TestPurgeAuditLog:
    @pytest.mark.asyncio
    async def test_purge_dry_run_no_delete(self) -> None:
        """--dry-run ne supprime aucune ligne."""
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=500)
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            from scripts.purge_audit_log import purge

            deleted = await purge(dry_run=True)

        assert deleted == 0
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_purge_deletes_old_rows(self) -> None:
        """La purge supprime les lignes anciennes par batch."""
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1500)
        # 1500 < BATCH_SIZE(10000) → un seul batch
        mock_conn.execute = AsyncMock(return_value="DELETE 1500")
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            from scripts.purge_audit_log import purge

            deleted = await purge(dry_run=False)

        assert deleted == 1500
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_purge_handles_large_volume(self) -> None:
        """La purge gère un volume > BATCH_SIZE en plusieurs itérations."""
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=25_000)

        call_count = 0

        async def _fake_execute(*args: Any, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "DELETE 10000"
            return "DELETE 5000"

        mock_conn.execute = _fake_execute
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            from scripts.purge_audit_log import purge

            deleted = await purge(dry_run=False)

        assert deleted == 25_000
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_purge_keeps_recent_events(self) -> None:
        """Si aucune ligne n'est ancienne, la purge ne fait rien."""
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            from scripts.purge_audit_log import purge

            deleted = await purge(dry_run=False)

        assert deleted == 0
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_purge_dry_run_reports_count_without_deleting(self) -> None:
        """--dry-run retourne 0 même quand il y a des lignes à purger."""
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=999)
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            from scripts.purge_audit_log import purge

            deleted = await purge(dry_run=True)

        assert deleted == 0
        mock_conn.execute.assert_not_called()
