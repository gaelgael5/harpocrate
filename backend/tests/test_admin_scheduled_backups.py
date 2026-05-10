"""Tests des endpoints /v1/admin/scheduled-backups."""

from __future__ import annotations

import base64
import datetime
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient


_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_SCHED_ID = uuid.UUID("22222222-0000-0000-0000-000000000001")
_REMOTE_ID = uuid.UUID("33333333-0000-0000-0000-000000000001")


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


def _admin_jwt() -> str:
    from app.core.config import settings

    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    payload = {
        "sub": "admin",
        "email": "admin@test",
        "name": "Admin",
        "iat": now,
        "exp": now + 3600,
        "iss": "harpocrate-local",
        "aud": settings.keycloak_client_id,
        "realm_access": {"roles": [settings.admin_role_name]},
    }
    secret = base64.b64decode(settings.hmac_key)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_jwt()}"}


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fake_schedule_dto(remote_id: uuid.UUID | None = None) -> Any:
    """DTO svc.ScheduledBackup mocké."""
    dto = MagicMock()
    dto.id = _SCHED_ID
    dto.name = "Daily 2h"
    dto.cron_expression = "0 2 * * *"
    dto.remote_id = remote_id
    dto.miss_threshold_minutes = 5
    dto.enabled = True
    dto.description = None
    dto.next_run_at = "2026-01-02T02:00:00+00:00"
    dto.last_run_at = None
    dto.last_run_status = None
    dto.last_run_error = None
    dto.remote_id_disconnected_at = None
    dto.created_at = "2026-01-01T00:00:00+00:00"
    dto.updated_at = "2026-01-01T00:00:00+00:00"
    dto.to_dict = MagicMock(
        return_value={
            "id": str(_SCHED_ID),
            "name": "Daily 2h",
            "cron_expression": "0 2 * * *",
            "remote_id": str(remote_id) if remote_id else None,
            "miss_threshold_minutes": 5,
            "enabled": True,
            "description": None,
            "next_run_at": "2026-01-02T02:00:00+00:00",
            "last_run_at": None,
            "last_run_status": None,
            "last_run_error": None,
            "remote_id_disconnected_at": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    return dto


# ─── Auth ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_admin() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/scheduled-backups")
    assert r.status_code in (401, 403)


# ─── List ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_schedules(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    async def _list(c: Any) -> list:
        return [_fake_schedule_dto()]

    monkeypatch.setattr(svc, "list_schedules", _list)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.get("/v1/admin/scheduled-backups", headers=_admin_header())

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["schedules"]) == 1
    assert body["schedules"][0]["name"] == "Daily 2h"


# ─── Create ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_id_local_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    captured: dict[str, Any] = {}

    async def _create(conn: Any, **kwargs: Any) -> uuid.UUID:
        captured.update(kwargs)
        return _SCHED_ID

    monkeypatch.setattr(svc, "create_schedule", _create)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/scheduled-backups",
            headers=_admin_header(),
            json={
                "name": "Daily 2h",
                "cron_expression": "0 2 * * *",
                "remote_id": None,
                "miss_threshold_minutes": 5,
                "description": None,
                "enabled": True,
            },
        )
    assert r.status_code == 201, r.text
    assert r.json() == {"id": str(_SCHED_ID)}
    assert captured["remote_id"] is None
    assert captured["miss_threshold_minutes"] == 5


@pytest.mark.asyncio
async def test_create_with_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    captured: dict[str, Any] = {}

    async def _create(conn: Any, **kwargs: Any) -> uuid.UUID:
        captured.update(kwargs)
        return _SCHED_ID

    monkeypatch.setattr(svc, "create_schedule", _create)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/scheduled-backups",
            headers=_admin_header(),
            json={
                "name": "Daily 2h to OVH",
                "cron_expression": "0 2 * * *",
                "remote_id": str(_REMOTE_ID),
                "miss_threshold_minutes": 30,
            },
        )
    assert r.status_code == 201, r.text
    assert captured["remote_id"] == _REMOTE_ID
    assert captured["miss_threshold_minutes"] == 30


@pytest.mark.asyncio
async def test_create_invalid_cron_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    async def _create(conn: Any, **kwargs: Any) -> uuid.UUID:
        raise ValueError("invalid cron expression: bad")

    monkeypatch.setattr(svc, "create_schedule", _create)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/scheduled-backups",
            headers=_admin_header(),
            json={"name": "X", "cron_expression": "not-a-cron"},
        )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid_payload"


@pytest.mark.asyncio
async def test_create_duplicate_name_returns_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduled_backups as svc

    async def _create(conn: Any, **kwargs: Any) -> uuid.UUID:
        raise Exception("duplicate key value violates unique 23505")

    monkeypatch.setattr(svc, "create_schedule", _create)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/scheduled-backups",
            headers=_admin_header(),
            json={"name": "X", "cron_expression": "0 2 * * *"},
        )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "name_already_exists"


# ─── Patch ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_updates_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    async def _get(c: Any, sid: uuid.UUID) -> Any:
        return _fake_schedule_dto()

    captured: dict[str, Any] = {}

    async def _update(conn: Any, **kwargs: Any) -> int:
        captured.update(kwargs)
        return 1

    monkeypatch.setattr(svc, "get_schedule", _get)
    monkeypatch.setattr(svc, "update_schedule", _update)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.patch(
            f"/v1/admin/scheduled-backups/{_SCHED_ID}",
            headers=_admin_header(),
            json={"enabled": False, "miss_threshold_minutes": 10},
        )
    assert r.status_code == 200, r.text
    assert captured["enabled"] is False
    assert captured["miss_threshold_minutes"] == 10


@pytest.mark.asyncio
async def test_patch_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    async def _get(c: Any, sid: uuid.UUID) -> Any:
        return None

    monkeypatch.setattr(svc, "get_schedule", _get)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.patch(
            f"/v1/admin/scheduled-backups/{_SCHED_ID}",
            headers=_admin_header(),
            json={"enabled": False},
        )
    assert r.status_code == 404


# ─── Delete ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc

    async def _delete(c: Any, sid: uuid.UUID) -> int:
        return 1

    monkeypatch.setattr(svc, "delete_schedule", _delete)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.delete(
            f"/v1/admin/scheduled-backups/{_SCHED_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_returns_404_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduled_backups as svc

    async def _delete(c: Any, sid: uuid.UUID) -> int:
        return 0

    monkeypatch.setattr(svc, "delete_schedule", _delete)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.delete(
            f"/v1/admin/scheduled-backups/{_SCHED_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404


# ─── Validate cron ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_cron_valid_returns_3_occurrences() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/scheduled-backups/validate-cron",
            headers=_admin_header(),
            json={"cron_expression": "0 2 * * *"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert len(body["next_3_occurrences"]) == 3
    assert body["error"] is None


@pytest.mark.asyncio
async def test_validate_cron_invalid_returns_error() -> None:
    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            "/v1/admin/scheduled-backups/validate-cron",
            headers=_admin_header(),
            json={"cron_expression": "not-a-cron"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False
    assert body["error"] is not None
    assert body["next_3_occurrences"] == []


# ─── Run-now ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_now_returns_503_if_scheduler_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduled_backups_scheduler as scheduler_svc

    monkeypatch.setattr(scheduler_svc, "_scheduler", None)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            f"/v1/admin/scheduled-backups/{_SCHED_ID}/run-now",
            headers=_admin_header(),
        )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "scheduler_not_started"


@pytest.mark.asyncio
async def test_run_now_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import scheduled_backups as svc
    from app.services import scheduled_backups_scheduler as scheduler_svc

    fake_scheduler = MagicMock()
    fake_scheduler.run_now = AsyncMock(
        return_value=svc.RunResult(
            status="ok",
            backup_id=uuid.UUID("44444444-0000-0000-0000-000000000001"),
            bytes_pushed=1024,
        )
    )
    monkeypatch.setattr(scheduler_svc, "_scheduler", fake_scheduler)

    conn = MagicMock()
    async with _client(_make_pool(conn)) as cli:
        r = await cli.post(
            f"/v1/admin/scheduled-backups/{_SCHED_ID}/run-now",
            headers=_admin_header(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["backup_id"] == "44444444-0000-0000-0000-000000000001"
    assert body["bytes_pushed"] == 1024
