"""Tests service pairing v2 (LOT 5 — échange d'URL signée)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from app.services import pairing as svc_v1
from app.services import pairing_v2 as svc
from app.services.pairing_url_codec import (
    InvalidPairingUrlError,
    build_pairing_url,
)


def _token_from_pairing_url(pairing_url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(pairing_url).query)
    return qs["t"][0]


async def _cleanup_repl_roles(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE usename LIKE 'repl_%'"
    )
    roles = await conn.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'")
    for r in roles:
        await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")


async def test_init_master_v2_returns_pairing_url(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        result = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            assert result.session_id is not None
            assert result.expires_in_seconds > 0
            assert "/pair?sid=" in result.pairing_url
            assert "&t=" in result.pairing_url
        finally:
            await conn.execute(
                "DELETE FROM pairing_session WHERE id = $1",
                result.session_id,
            )
            await conn.execute(
                "DELETE FROM audit_log WHERE action = 'pairing.master_init_v2' "
                "AND created_at >= now() - interval '1 minute'"
            )


async def test_init_master_v2_rejects_invalid_standby_url(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.PairingAcceptError):
            await svc.init_master_v2(
                conn,
                standby_url="not-an-url",
                actor_user_id=None,
            )
        with pytest.raises(svc_v1.PairingAcceptError):
            await svc.init_master_v2(
                conn,
                standby_url="",
                actor_user_id=None,
            )


async def test_confirm_master_v2_invalid_session_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    from uuid import uuid4

    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.confirm_master_v2(
                conn,
                session_id=uuid4(),
                token="a" * 32,
                standby_url="https://b/",
                actor_user_id=None,
            )


async def test_confirm_master_v2_token_mismatch_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        init = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            with pytest.raises(svc_v1.InvalidCodeError):
                await svc.confirm_master_v2(
                    conn,
                    session_id=init.session_id,
                    token="0" * 32,
                    standby_url="https://b.example/",
                    actor_user_id=None,
                )
        finally:
            await conn.execute(
                "DELETE FROM pairing_session WHERE id = $1",
                init.session_id,
            )
            await conn.execute(
                "DELETE FROM audit_log WHERE action IN "
                "('pairing.master_init_v2', 'pairing.failed') "
                "AND created_at >= now() - interval '1 minute'"
            )


async def test_accept_standby_v2_invalid_url_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(InvalidPairingUrlError):
            await svc.accept_standby_v2(
                conn,
                pairing_url="https://master/wrong-path?foo=bar",
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_v2_network_error_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Master injoignable → PairingAcceptError."""
    from uuid import uuid4

    url = build_pairing_url("https://does-not-exist.invalid", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.PairingAcceptError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_v2_invalid_token_raises_invalid_code(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """403 du master → InvalidCodeError."""
    from uuid import uuid4

    fake_resp = MagicMock()
    fake_resp.status_code = 403

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.post = AsyncMock(return_value=fake_resp)

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )


async def test_accept_standby_v2_verify_tls_default_strict(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Par défaut, httpx.AsyncClient est instancié avec verify=True."""
    from uuid import uuid4

    captured: dict[str, object] = {}

    def fake_async_client(*args: object, **kwargs: object) -> AsyncMock:
        captured.update(kwargs)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        resp = MagicMock()
        resp.status_code = 403
        client.post = AsyncMock(return_value=resp)
        return client

    monkeypatch.setattr(svc.httpx, "AsyncClient", fake_async_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )
    assert captured.get("verify") is True


async def test_accept_standby_v2_verify_tls_disabled_when_setting_true(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Quand insecure_skip_tls_verify=True, verify=False et un warning est loggé."""
    from uuid import uuid4

    from app.core.config import settings

    monkeypatch.setattr(settings, "replication_insecure_skip_tls_verify", True)

    captured: dict[str, object] = {}

    def fake_async_client(*args: object, **kwargs: object) -> AsyncMock:
        captured.update(kwargs)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        resp = MagicMock()
        resp.status_code = 403
        client.post = AsyncMock(return_value=resp)
        return client

    monkeypatch.setattr(svc.httpx, "AsyncClient", fake_async_client)

    warnings: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        svc.logger,
        "warning",
        lambda event, **kw: warnings.append((event, kw)),
    )

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.InvalidCodeError):
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )
    assert captured.get("verify") is False
    assert any(ev == "pairing_v2.tls_verification_disabled" for ev, _ in warnings)


async def test_confirm_master_v2_raises_node_already_exists_on_label_collision(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Si un node existe déjà pour ce standby_url, on lève NodeAlreadyExistsError."""
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import replication_strategies as strat_repo
        from app.services import streaming_replication as streaming_svc

        strat_id = await strat_repo.upsert_strategy(
            conn,
            type_="docker_compose",
            label=f"test-strategy-{__import__('uuid').uuid4().hex[:8]}",
            description="test",
            config={"compose_file": "/tmp/x.yml"},
        )
        await strat_repo.activate_strategy(conn, strategy_id=strat_id)

        # 1) crée un node existant pour b.example
        await streaming_svc.add_node(
            conn,
            strategy_id=strat_id,
            label="https://b.example/",
            host="b.example",
            port=5432,
            role="standby_ro",
            notes=None,
            master_host="a.example",
            master_port=5432,
            created_by_user_id=None,
        )

        # 2) prépare une session pending pour confirm_master_v2
        init = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            with pytest.raises(svc_v1.NodeAlreadyExistsError) as exc_info:
                await svc.confirm_master_v2(
                    conn,
                    session_id=init.session_id,
                    token=_token_from_pairing_url(init.pairing_url),
                    standby_url="https://b.example/",
                    actor_user_id=None,
                )
            assert "id" in exc_info.value.existing_node
            assert exc_info.value.existing_node["label"] == "https://b.example/"
        finally:
            await conn.execute("DELETE FROM pairing_session WHERE id = $1", init.session_id)
            await conn.execute("DELETE FROM replication_nodes WHERE strategy_id = $1", strat_id)
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            await _cleanup_repl_roles(conn)


async def test_accept_standby_v2_transmits_force_to_master(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """`force=True` doit apparaître dans le body POST vers /confirm-v2."""
    from uuid import uuid4

    captured: dict[str, object] = {}

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={
        "master_host": "a", "master_port": 5432,
        "replication_user": "repl_x", "replication_password": "p",
        "application_name": "x", "node_id": str(uuid4()),
    })
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    async def fake_post(url: str, json: dict[str, object]) -> MagicMock:
        captured["url"] = url
        captured["body"] = json
        return fake_resp

    fake_client.post = fake_post
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        await svc.accept_standby_v2(
            conn,
            pairing_url=url,
            self_url="https://b/",
            actor_user_id=None,
            force=True,
        )
    assert captured["body"]["force"] is True


async def test_accept_standby_v2_propagates_409_as_node_already_exists(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """409 du master → NodeAlreadyExistsError typée portant existing_node."""
    from uuid import uuid4

    fake_resp = MagicMock()
    fake_resp.status_code = 409
    fake_resp.json = MagicMock(return_value={
        "detail": {
            "error": "node_already_exists",
            "existing_node": {
                "id": str(uuid4()),
                "label": "https://b/",
                "host": "b",
                "application_name": "b",
                "last_state": "disconnected",
                "last_seen_at": "2026-05-10T12:00:00+00:00",
            },
        },
    })
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.post = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.NodeAlreadyExistsError) as exc_info:
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )
        assert exc_info.value.existing_node["host"] == "b"
        assert exc_info.value.existing_node["last_state"] == "disconnected"


async def test_confirm_master_v2_with_force_replaces_existing_node(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """`force=True` remplace le node existant et écrit l'audit `pairing.master_node_replaced`."""
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import replication_strategies as strat_repo
        from app.services import streaming_replication as streaming_svc

        strat_id = await strat_repo.upsert_strategy(
            conn,
            type_="docker_compose",
            label=f"test-strategy-{__import__('uuid').uuid4().hex[:8]}",
            description="test",
            config={"compose_file": "/tmp/x.yml"},
        )
        await strat_repo.activate_strategy(conn, strategy_id=strat_id)
        old_node_id, _ = await streaming_svc.add_node(
            conn,
            strategy_id=strat_id,
            label="https://b.example/",
            host="b.example",
            port=5432,
            role="standby_ro",
            notes=None,
            master_host="a.example",
            master_port=5432,
            created_by_user_id=None,
        )
        init = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            payload = await svc.confirm_master_v2(
                conn,
                session_id=init.session_id,
                token=_token_from_pairing_url(init.pairing_url),
                standby_url="https://b.example/",
                actor_user_id=None,
                force=True,
            )
            assert payload["master_host"]
            assert payload["replication_user"].startswith("repl_")
            # ancien node supprimé
            assert await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1", old_node_id
            ) is None
            # nouveau node créé
            new_row = await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1::uuid",
                payload["node_id"],
            )
            assert new_row is not None
            # audit log replacement
            audit = await conn.fetchrow(
                "SELECT * FROM audit_log "
                "WHERE action = 'pairing.master_node_replaced' "
                "AND created_at >= now() - interval '1 minute' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            assert audit is not None
        finally:
            await conn.execute("DELETE FROM pairing_session WHERE id = $1", init.session_id)
            await conn.execute("DELETE FROM replication_nodes WHERE strategy_id = $1", strat_id)
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            await conn.execute(
                "DELETE FROM audit_log WHERE action IN "
                "('pairing.master_init_v2', 'pairing.master_node_replaced') "
                "AND created_at >= now() - interval '1 minute'"
            )
            await _cleanup_repl_roles(conn)
