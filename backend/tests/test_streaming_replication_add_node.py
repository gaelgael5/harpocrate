"""Tests unitaires add_node — branches d'erreur (LOT 5 fix conflit label)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from app.db.repositories import replication_strategies as strat_repo
from app.services import pairing as svc_pairing
from app.services import streaming_replication as svc


async def _create_active_strategy(conn: asyncpg.Connection[asyncpg.Record]) -> str:
    sid = await strat_repo.upsert_strategy(
        conn,
        type_="docker_compose",
        label=f"test-strategy-{uuid.uuid4().hex[:8]}",
        description="test",
        config={"compose_file": "/tmp/x.yml"},
    )
    await strat_repo.activate_strategy(conn, strategy_id=sid)
    return sid


async def test_add_node_label_collision_raises_node_already_exists(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        strat_id = await _create_active_strategy(conn)
        try:
            node_id_1, _ = await svc.add_node(
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
            with pytest.raises(svc_pairing.NodeAlreadyExistsError) as exc_info:
                await svc.add_node(
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
            details = exc_info.value.existing_node
            assert details["id"] == str(node_id_1)
            assert details["label"] == "https://b.example/"
            assert details["host"] == "b.example"
            assert "application_name" in details
            assert "last_state" in details
            assert "last_seen_at" in details
        finally:
            await conn.execute(
                "DELETE FROM replication_nodes WHERE strategy_id = $1",
                strat_id,
            )
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE usename LIKE 'repl_%'"
            )
            roles = await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'"
            )
            for r in roles:
                await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")


async def test_add_node_with_replace_existing_replaces_collision(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        strat_id = await _create_active_strategy(conn)
        try:
            node_id_1, _bundle_1 = await svc.add_node(
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
            node_id_2, bundle_2 = await svc.add_node(
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
                replace_existing=True,
            )
            assert node_id_2 != node_id_1
            old = await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1", node_id_1
            )
            assert old is None  # ancienne row supprimée
            new = await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1", node_id_2
            )
            assert new is not None
            assert bundle_2.password != ""
        finally:
            await conn.execute(
                "DELETE FROM replication_nodes WHERE strategy_id = $1", strat_id
            )
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE usename LIKE 'repl_%'"
            )
            roles = await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'"
            )
            for r in roles:
                await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")
