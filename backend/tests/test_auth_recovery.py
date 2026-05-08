"""Tests endpoints /v1/auth/recovery (LOT_57.B)."""
from __future__ import annotations

import base64
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.test")


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


# ─── POST /start ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_returns_202_for_unknown_email() -> None:
    """Anti-énumération : 202 même si l'email n'existe pas."""
    from app.services import recovery as svc

    conn = MagicMock()
    pool = _make_pool(conn)

    with patch.object(svc, "start_session", AsyncMock(return_value=None)) as m:
        async with _client(pool) as cli:
            r = await cli.post(
                "/v1/auth/recovery/start",
                json={"email": "unknown@example.com"},
            )
    assert r.status_code == 202
    assert r.json() == {"ok": True}
    m.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_lowercases_email_before_passing_to_service() -> None:
    from app.services import recovery as svc

    conn = MagicMock()
    pool = _make_pool(conn)

    captured: dict[str, Any] = {}

    async def fake_start(_conn: Any, *, email: str, ip: str | None) -> None:
        captured["email"] = email
        captured["ip"] = ip

    with patch.object(svc, "start_session", AsyncMock(side_effect=fake_start)):
        async with _client(pool) as cli:
            r = await cli.post(
                "/v1/auth/recovery/start",
                json={"email": "Mixed.Case@Example.com"},
            )
    assert r.status_code == 202
    assert captured["email"] == "mixed.case@example.com"


@pytest.mark.asyncio
async def test_start_rejects_invalid_email_400() -> None:
    pool = _make_pool(MagicMock())
    async with _client(pool) as cli:
        r = await cli.post("/v1/auth/recovery/start", json={"email": "not-an-email"})
    assert r.status_code == 422  # Pydantic EmailStr validation


# ─── GET /{id} ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_blobs_when_session_valid() -> None:
    from app.services import recovery as svc

    blobs = svc.RecoveryBlobs(
        session_id=uuid4(),
        attempts_left=3,
        salt_recovery=b"a" * 16,
        encrypted_sym_key_by_recovery=b"b" * 32,
        salt_passphrase=b"c" * 16,
        encrypted_rsa_private_key=b"d" * 64,
        rsa_public_key=b"e" * 32,
        kdf_memory_kb=65536,
        kdf_iterations=3,
        kdf_parallelism=4,
    )
    pool = _make_pool(MagicMock())

    with patch.object(svc, "get_blobs", AsyncMock(return_value=blobs)):
        async with _client(pool) as cli:
            r = await cli.get(f"/v1/auth/recovery/{blobs.session_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["attempts_left"] == 3
    assert body["kdf_params"]["memory_kb"] == 65536
    assert "salt_recovery" in body


@pytest.mark.asyncio
async def test_get_returns_404_when_session_not_found() -> None:
    from app.services import recovery as svc

    pool = _make_pool(MagicMock())

    with patch.object(svc, "get_blobs", AsyncMock(side_effect=svc.SessionNotFoundError("nope"))):
        async with _client(pool) as cli:
            r = await cli.get(f"/v1/auth/recovery/{uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_returns_410_when_session_expired_or_failed() -> None:
    from app.services import recovery as svc

    pool = _make_pool(MagicMock())

    with patch.object(
        svc, "get_blobs", AsyncMock(side_effect=svc.SessionInvalidError("session_expired"))
    ):
        async with _client(pool) as cli:
            r = await cli.get(f"/v1/auth/recovery/{uuid4()}")
    assert r.status_code == 410
    assert r.json()["detail"]["error"] == "session_expired"


# ─── POST /{id}/attempt-failed ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attempt_failed_returns_attempts_left() -> None:
    from app.services import recovery as svc

    pool = _make_pool(MagicMock())

    with patch.object(svc, "record_failed_attempt", AsyncMock(return_value=2)):
        async with _client(pool) as cli:
            r = await cli.post(f"/v1/auth/recovery/{uuid4()}/attempt-failed")
    assert r.status_code == 200
    assert r.json() == {"attempts_left": 2}


@pytest.mark.asyncio
async def test_attempt_failed_returns_410_when_session_failed() -> None:
    from app.services import recovery as svc

    pool = _make_pool(MagicMock())

    with patch.object(
        svc,
        "record_failed_attempt",
        AsyncMock(side_effect=svc.SessionInvalidError("session_failed")),
    ):
        async with _client(pool) as cli:
            r = await cli.post(f"/v1/auth/recovery/{uuid4()}/attempt-failed")
    assert r.status_code == 410


# ─── POST /{id}/complete ──────────────────────────────────────────────────────


def _valid_complete_body() -> dict[str, Any]:
    return {
        "new_salt_passphrase": base64.b64encode(b"s" * 16).decode(),
        "new_encrypted_rsa_private_key": base64.b64encode(b"k" * 64).decode(),
        "new_encrypted_sym_key_by_pass": base64.b64encode(b"y" * 48).decode(),
        "kdf_memory_kb": 65536,
        "kdf_iterations": 3,
        "kdf_parallelism": 4,
    }


@pytest.mark.asyncio
async def test_complete_ok() -> None:
    from app.services import recovery as svc

    pool = _make_pool(MagicMock())

    with patch.object(svc, "complete_session", AsyncMock(return_value=None)) as m:
        async with _client(pool) as cli:
            r = await cli.post(
                f"/v1/auth/recovery/{uuid4()}/complete",
                json=_valid_complete_body(),
            )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    m.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_rejects_wrong_salt_size() -> None:
    pool = _make_pool(MagicMock())
    body = _valid_complete_body()
    body["new_salt_passphrase"] = base64.b64encode(b"x" * 8).decode()  # 8, pas 16

    async with _client(pool) as cli:
        r = await cli.post(f"/v1/auth/recovery/{uuid4()}/complete", json=body)
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_salt_size"


@pytest.mark.asyncio
async def test_complete_returns_410_on_consumed() -> None:
    from app.services import recovery as svc

    pool = _make_pool(MagicMock())

    with patch.object(
        svc,
        "complete_session",
        AsyncMock(side_effect=svc.SessionInvalidError("session_consumed")),
    ):
        async with _client(pool) as cli:
            r = await cli.post(
                f"/v1/auth/recovery/{uuid4()}/complete",
                json=_valid_complete_body(),
            )
    assert r.status_code == 410


# ─── Service unit tests (worker + service start_session) ──────────────────────


@pytest.mark.asyncio
async def test_service_start_skips_novu_for_unknown_email() -> None:
    """Si l'email n'existe pas, aucune notification ne part — mais la session
    est quand même créée pour anti-énumération + count anomalie."""
    from app.db.repositories import recovery_sessions as repo
    from app.services import notify_novu
    from app.services import recovery as svc

    conn = MagicMock()
    new_id = uuid4()
    with patch.object(repo, "insert", AsyncMock(return_value=new_id)) as ins, patch(
        "app.services.recovery.users_repo.get_id_and_is_system_by_email",
        AsyncMock(return_value=None),
    ), patch.object(notify_novu, "trigger_event", AsyncMock()) as trig:
        await svc.start_session(conn, email="ghost@example.com", ip="1.2.3.4")

    ins.assert_awaited_once()
    trig.assert_not_called()


@pytest.mark.asyncio
async def test_service_start_skips_novu_for_system_user() -> None:
    """Le local-admin (is_system=True) n'a pas de matériel crypto → pas de
    workflow recovery déclenché."""
    from app.db.repositories import recovery_sessions as repo
    from app.services import notify_novu
    from app.services import recovery as svc

    conn = MagicMock()
    user_id = uuid4()
    new_id = uuid4()
    with patch.object(repo, "insert", AsyncMock(return_value=new_id)), patch(
        "app.services.recovery.users_repo.get_id_and_is_system_by_email",
        AsyncMock(return_value=(user_id, True)),
    ), patch.object(notify_novu, "trigger_event", AsyncMock()) as trig:
        await svc.start_session(conn, email="admin@harpocrate.local", ip=None)

    trig.assert_not_called()


@pytest.mark.asyncio
async def test_increment_attempts_flips_to_failed_at_three() -> None:
    """L'attempt #3 doit faire passer la session en status='failed'."""
    from app.db.repositories import recovery_sessions as repo

    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=3)

    new_attempts = await repo.increment_attempts(conn, uuid4())
    assert new_attempts == 3
    # vérifie que le SQL contient bien le CASE qui flip à 'failed'
    sql = conn.fetchval.await_args.args[0]
    assert "'failed'" in sql
    assert "attempts + 1 >= 3" in sql


@pytest.mark.asyncio
async def test_anomaly_recorded_when_threshold_reached() -> None:
    """5 sessions failed/expired sur 24h → INSERT identity_anomaly_events."""
    from app.db.repositories import recovery_sessions as repo
    from app.services import notify_novu
    from app.services import recovery as svc

    conn = MagicMock()
    user_id = uuid4()
    new_session_id = uuid4()

    inserts: list[Any] = []

    async def fake_execute(*args: Any) -> str:
        inserts.append(args)
        return "INSERT 0 1"

    conn.execute = AsyncMock(side_effect=fake_execute)
    conn.fetchval = AsyncMock(return_value="Gael")  # display_name lookup

    with patch.object(repo, "insert", AsyncMock(return_value=new_session_id)), patch(
        "app.services.recovery.users_repo.get_id_and_is_system_by_email",
        AsyncMock(return_value=(user_id, False)),
    ), patch.object(
        repo,
        "count_unsuccessful_for_email",
        AsyncMock(return_value=5),
    ), patch.object(notify_novu, "trigger_event", AsyncMock()):
        await svc.start_session(conn, email="g@example.com", ip=None)

    # Au moins un INSERT identity_anomaly_events doit avoir eu lieu.
    sqls = [str(call[0]) for call in inserts]
    assert any("identity_anomaly_events" in sql for sql in sqls)


@pytest.mark.asyncio
async def test_record_failed_attempt_logs_audit_at_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """À 3 tentatives, la session passe failed ET un audit_log est inséré.

    On patche directement le binding `audit_log_insert` *importé dans
    recovery.py* (pas dans audit.py source) — un `from x import y` crée
    un binding local dans le module appelant, donc patcher la source
    n'a aucun effet sur l'appelant.
    """
    from app.db.repositories import recovery_sessions as repo
    from app.services import recovery as svc

    conn = MagicMock()
    user_id = uuid4()
    session_id = uuid4()

    conn.fetchval = AsyncMock(return_value=3)
    audit_mock = AsyncMock()
    monkeypatch.setattr(svc, "audit_log_insert", audit_mock)

    with patch.object(
        repo,
        "get_by_id",
        AsyncMock(return_value={
            "id": session_id,
            "user_id": user_id,
            "email": "g@y",
            "created_at": datetime.datetime.now(datetime.UTC),
            "expires_at": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
            "status": "failed",
            "attempts": 3,
            "ip_started": None,
            "ip_consumed": None,
            "consumed_at": None,
        }),
    ):
        attempts_left = await svc.record_failed_attempt(conn, session_id)
    assert attempts_left == 0
    audit_mock.assert_awaited_once()
    args = audit_mock.await_args
    assert args.args[1] == "user.recovery_session_exhausted"


@pytest.mark.asyncio
async def test_complete_session_inserts_audit_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Après reset réussi, un audit `passphrase_reset_via_recovery` est tracé."""
    from app.db.repositories import recovery_sessions as repo
    from app.db.repositories import users as users_repo
    from app.services import recovery as svc

    conn = MagicMock()
    user_id = uuid4()
    session_id = uuid4()
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=20)

    audit_mock = AsyncMock()
    monkeypatch.setattr(svc, "audit_log_insert", audit_mock)

    with patch.object(
        repo,
        "get_by_id",
        AsyncMock(return_value={
            "id": session_id,
            "user_id": user_id,
            "email": "g@y",
            "created_at": datetime.datetime.now(datetime.UTC),
            "expires_at": future,
            "status": "pending",
            "attempts": 0,
            "ip_started": None,
            "ip_consumed": None,
            "consumed_at": None,
        }),
    ), patch.object(users_repo, "update_passphrase", AsyncMock()), patch.object(
        repo, "mark_consumed", AsyncMock()
    ):
        await svc.complete_session(
            conn,
            session_id=session_id,
            new_salt_passphrase=b"s" * 16,
            new_encrypted_rsa_private_key=b"k" * 64,
            new_encrypted_sym_key_by_pass=b"y" * 48,
            kdf_memory_kb=65536,
            kdf_iterations=3,
            kdf_parallelism=4,
            ip="1.2.3.4",
        )
    audit_mock.assert_awaited_once()
    args = audit_mock.await_args
    assert args.args[1] == "user.passphrase_reset_via_recovery"


@pytest.mark.asyncio
async def test_get_blobs_raises_410_when_expired() -> None:
    from app.db.repositories import recovery_sessions as repo
    from app.services import recovery as svc

    conn = MagicMock()
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    with patch.object(
        repo,
        "get_by_id",
        AsyncMock(return_value={
            "id": uuid4(),
            "user_id": uuid4(),
            "email": "x@y",
            "created_at": past,
            "expires_at": past,
            "status": "pending",
            "attempts": 0,
            "ip_started": None,
            "ip_consumed": None,
            "consumed_at": None,
        }),
    ), pytest.raises(svc.SessionInvalidError) as exc:
        await svc.get_blobs(conn, uuid4())
    assert exc.value.reason == "session_expired"
