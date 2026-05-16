"""Tests endpoints /v1/admin/replication/{can-promote,promote} (failover MVP)."""

from __future__ import annotations

import base64
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "test-client")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_ENABLED", "true")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_USERNAME", "admin")
    monkeypatch.setenv("HARPOCRATE_ADMIN_LOCAL_PASSWORD", "test-password")
    import app.core.config
    app.core.config.settings = app.core.config.Settings()


def _admin_token() -> str:
    from app.core.config import settings
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    payload = {
        "sub": "admin",
        "email": "admin@test",
        "iat": now,
        "exp": now + 3600,
        "iss": "harpocrate-local",
        "aud": settings.keycloak_client_id,
        "realm_access": {"roles": [settings.admin_role_name]},
    }
    secret = base64.b64decode(settings.hmac_key)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_token()}"}


def _make_pool() -> MagicMock:
    """Pool factice — les endpoints promote n'utilisent pas la conn directement
    (le service est mocké), mais `acquire()` doit retourner un context manager."""

    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return MagicMock()

        async def __aexit__(self, *_a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


def _client() -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = _make_pool()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_can_promote_returns_200_when_standby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /can-promote → 200 avec can_promote=true quand en mode standby."""
    from app.services.streaming_replication import PromoteEligibility

    monkeypatch.setattr(
        "app.services.streaming_replication.get_promote_eligibility",
        AsyncMock(
            return_value=PromoteEligibility(
                can_promote=True,
                current_role="standby",
                master_url="https://master.example/",
                reason_if_not=None,
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.get(
            "/v1/admin/replication/can-promote", headers=_admin_header()
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_promote"] is True
    assert body["current_role"] == "standby"
    assert body["master_url"] == "https://master.example/"


@pytest.mark.asyncio
async def test_can_promote_returns_false_when_already_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.streaming_replication import PromoteEligibility

    monkeypatch.setattr(
        "app.services.streaming_replication.get_promote_eligibility",
        AsyncMock(
            return_value=PromoteEligibility(
                can_promote=False,
                current_role="master",
                master_url="https://old/",
                reason_if_not="already_master",
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.get(
            "/v1/admin/replication/can-promote", headers=_admin_header()
        )
    assert r.status_code == 200
    body = r.json()
    assert body["can_promote"] is False
    assert body["current_role"] == "master"
    assert body["reason_if_not"] == "already_master"


@pytest.mark.asyncio
async def test_promote_returns_200_when_confirmations_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /promote → 200 + promoted=true quand confirmations OK et standby."""
    from app.services.streaming_replication import PromoteResult

    monkeypatch.setattr(
        "app.services.streaming_replication.promote_standby_to_master",
        AsyncMock(
            return_value=PromoteResult(
                promoted=True, old_master_url="https://old-master/"
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.post(
            "/v1/admin/replication/promote",
            json={
                "confirm_master_down": True,
                "confirm_clients_will_be_reconfigured": True,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["promoted"] is True
    assert body["old_master_url"] == "https://old-master/"


@pytest.mark.asyncio
async def test_promote_returns_400_when_confirm_master_down_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refus si confirm_master_down=False."""
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.post(
            "/v1/admin/replication/promote",
            json={
                "confirm_master_down": False,
                "confirm_clients_will_be_reconfigured": True,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "missing_confirmation"


@pytest.mark.asyncio
async def test_promote_returns_400_when_confirm_clients_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.post(
            "/v1/admin/replication/promote",
            json={
                "confirm_master_down": True,
                "confirm_clients_will_be_reconfigured": False,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_promote_returns_409_when_already_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si le service lève NotInStandbyModeError → 409."""
    from app.services.streaming_replication import NotInStandbyModeError

    monkeypatch.setattr(
        "app.services.streaming_replication.promote_standby_to_master",
        AsyncMock(side_effect=NotInStandbyModeError("not_in_recovery")),
    )
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.post(
            "/v1/admin/replication/promote",
            json={
                "confirm_master_down": True,
                "confirm_clients_will_be_reconfigured": True,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_in_standby_mode"


@pytest.mark.asyncio
async def test_promote_returns_500_when_promotion_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si pg_promote n'a pas sorti l'instance du recovery → 500 promotion_failed."""
    from app.services.streaming_replication import PromotionFailedError

    monkeypatch.setattr(
        "app.services.streaming_replication.promote_standby_to_master",
        AsyncMock(side_effect=PromotionFailedError("timeout")),
    )
    monkeypatch.setattr(
        "app.services.admin_user_resolver.resolve_admin_user_id",
        AsyncMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    async with _client() as client:
        r = await client.post(
            "/v1/admin/replication/promote",
            json={
                "confirm_master_down": True,
                "confirm_clients_will_be_reconfigured": True,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "promotion_failed"


@pytest.mark.asyncio
async def test_can_promote_requires_admin_auth() -> None:
    """GET /can-promote sans JWT → 401."""
    async with _client() as client:
        r = await client.get("/v1/admin/replication/can-promote")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_promote_requires_admin_auth() -> None:
    """POST /promote sans JWT → 401."""
    async with _client() as client:
        r = await client.post(
            "/v1/admin/replication/promote",
            json={
                "confirm_master_down": True,
                "confirm_clients_will_be_reconfigured": True,
            },
        )
    assert r.status_code == 401
