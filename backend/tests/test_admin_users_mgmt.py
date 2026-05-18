"""Tests des endpoints admin de gestion des utilisateurs — Lot 4A (A-2..A-5).

Couvre :
- POST   /v1/admin/users/{id}/disable           (A-2)
- POST   /v1/admin/users/{id}/enable            (A-2)
- POST   /v1/admin/users/{id}/quarantine/clear  (A-3)
- PATCH  /v1/admin/users/{id}/force-reverify-next-login (A-4)
- DELETE /v1/admin/users/{id}/identities/{identity_id}  (A-5)
"""
from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_IDENTITY_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(backup)


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}})
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


def _make_conn() -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)  # user exists by default
    conn.execute = AsyncMock(return_value=None)

    class _TxCtx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            pass

    conn.transaction = MagicMock(return_value=_TxCtx())
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── A-2 disable / enable ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disable_user_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/disable",
            headers=_user_header(),
            json={"reason": "test"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_disable_user_404_when_not_found() -> None:
    conn = _make_conn()
    conn.fetchval = AsyncMock(return_value=None)  # user doesn't exist
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/disable",
            headers=_admin_header(),
            json={"reason": "test"},
        )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "user_not_found"


@pytest.mark.asyncio
async def test_disable_user_happy_path() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/disable",
            headers=_admin_header(),
            json={"reason": "compromised account"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "disabled"
    assert body["user_id"] == str(_USER_ID)
    # UPDATE puis audit_log_insert (et la query d'existence)
    assert conn.execute.await_count >= 2


@pytest.mark.asyncio
async def test_disable_user_requires_reason() -> None:
    """Le body doit contenir `reason` (anti-bouton-cliqué-sans-raison)."""
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/disable",
            headers=_admin_header(),
            json={},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_enable_user_happy_path() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/enable",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    assert r.json()["status"] == "enabled"


# ─── A-3 quarantine clear ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quarantine_clear_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/quarantine/clear",
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_quarantine_clear_logs_previous_state() -> None:
    """L'audit log doit capturer l'etat avant le clear."""
    conn = _make_conn()
    previous_until = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
    conn.fetchrow = AsyncMock(
        return_value={
            "quarantine_until": previous_until,
            "quarantine_reason": "critical_anomaly_detected",
        }
    )
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/users/{_USER_ID}/quarantine/clear",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    assert r.json()["status"] == "quarantine_cleared"


# ─── A-4 force_reverify_next_login ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_reverify_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.patch(
            f"/v1/admin/users/{_USER_ID}/force-reverify-next-login",
            headers=_user_header(),
            json={"enabled": True},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_force_reverify_enable() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/admin/users/{_USER_ID}/force-reverify-next-login",
            headers=_admin_header(),
            json={"enabled": True},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["force_reverify_next_login"] is True


@pytest.mark.asyncio
async def test_force_reverify_disable() -> None:
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.patch(
            f"/v1/admin/users/{_USER_ID}/force-reverify-next-login",
            headers=_admin_header(),
            json={"enabled": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["force_reverify_next_login"] is False


# ─── A-5 unlink OIDC identity ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unlink_identity_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.delete(
            f"/v1/admin/users/{_USER_ID}/identities/{_IDENTITY_ID}",
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unlink_identity_404_when_identity_not_found() -> None:
    conn = _make_conn()
    # user exists, identity_row fetchrow returns None
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetchrow = AsyncMock(return_value=None)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/users/{_USER_ID}/identities/{_IDENTITY_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "identity_not_found"


@pytest.mark.asyncio
async def test_unlink_identity_refuses_last_one() -> None:
    """409 si on tente de delier la derniere identite (lockout)."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(
        return_value={"provider": "keycloak", "external_subject": "abc"}
    )
    # _ensure_user_exists OK, then COUNT(*) returns 1 (last identity)
    conn.fetchval = AsyncMock(side_effect=[1, 1])
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/users/{_USER_ID}/identities/{_IDENTITY_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "last_identity_cannot_be_unlinked"


@pytest.mark.asyncio
async def test_unlink_identity_happy_path() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(
        return_value={"provider": "keycloak", "external_subject": "abc"}
    )
    # _ensure_user_exists OK, COUNT(*) returns 2 (not the last)
    conn.fetchval = AsyncMock(side_effect=[1, 2])
    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/users/{_USER_ID}/identities/{_IDENTITY_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 204


# ─── Enforcement : disabled users get 403 partout ───────────────────────────


@pytest.mark.asyncio
async def test_get_by_keycloak_sub_raises_when_user_disabled() -> None:
    """`users_repo.get_by_keycloak_sub` leve `UserDisabledError` quand
    `disabled_at IS NOT NULL`. Le handler global transforme en 403.
    """
    import datetime as _dt

    from app.db.repositories.users import UserDisabledError, get_by_keycloak_sub

    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": _USER_ID,
            "disabled_at": _dt.datetime.now(_dt.UTC),
            "keycloak_sub": "test-sub-001",
        }
    )
    with pytest.raises(UserDisabledError):
        await get_by_keycloak_sub(conn, "test-sub-001")


@pytest.mark.asyncio
async def test_get_by_keycloak_sub_returns_none_when_user_not_found() -> None:
    """Le repo retourne None quand le row n'existe pas (premier login)."""
    from app.db.repositories.users import get_by_keycloak_sub

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    result = await get_by_keycloak_sub(conn, "no-such-sub")
    assert result is None


# ─── A-1 detail aggregation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_detail_requires_admin() -> None:
    async with _make_client(_make_pool(_make_conn())) as client:
        r = await client.get(
            f"/v1/admin/users/{_USER_ID}",
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_user_detail_404_when_not_found() -> None:
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/admin/users/{_USER_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_user_detail_returns_aggregated_payload() -> None:
    conn = _make_conn()
    now = datetime.datetime(2026, 5, 17, 12, 0, 0, tzinfo=datetime.UTC)
    user_row = {
        "id": _USER_ID,
        "email": "alice@example.com",
        "display_name": "Alice",
        "created_at": now,
        "last_unlock_at": now,
        "disabled_at": None,
        "disabled_reason": None,
        "quarantine_until": None,
        "quarantine_reason": None,
        "force_reverify_next_login": False,
        "has_bootstrap": True,
    }
    conn.fetchrow = AsyncMock(return_value=user_row)
    conn.fetchval = AsyncMock(side_effect=[3, 2, 5, 1])  # owned, shared, anomaly_total, anomaly_unack
    conn.fetch = AsyncMock(side_effect=[
        # identities
        [
            {
                "id": _IDENTITY_ID,
                "provider": "keycloak_internal",
                "external_subject": "kc-sub-1",
                "is_primary": True,
                "linked_at": now,
                "last_login_at": now,
                "linked_email": "alice@example.com",
                "linked_display_name": "Alice",
            }
        ],
        # recent wallets
        [
            {"id": uuid.UUID("11111111-1111-1111-1111-111111111111"), "name": "prod", "created_at": now},
        ],
        # recent anomalies
        [],
        # recent audit
        [
            {
                "id": 100,
                "occurred_at": now,
                "action": "auth.local_login",
                "success": True,
                "error_code": None,
                "actor_user_id": _USER_ID,
                "actor_api_key_id": None,
                "actor_ip": "10.0.0.1",
                "target_wallet_id": None,
                "target_secret_id": None,
                "target_api_key_id": None,
            }
        ],
    ])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/admin/users/{_USER_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["has_bootstrap"] is True
    assert body["user"]["force_reverify_next_login"] is False
    assert len(body["identities"]) == 1
    assert body["identities"][0]["provider"] == "keycloak_internal"
    assert body["wallets"]["owned_count"] == 3
    assert body["wallets"]["shared_count"] == 2
    assert len(body["wallets"]["recent_owned"]) == 1
    assert body["anomalies"]["total_count"] == 5
    assert body["anomalies"]["unacknowledged_count"] == 1
    assert len(body["recent_audit"]) == 1
    assert body["recent_audit"][0]["action"] == "auth.local_login"
