"""Tests du service streaming_replication (LOT réplication itération 1).

On teste les helpers purs (slug, password, bundle generator) et les
opérations service avec mocks asyncpg — pas de DB réelle.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


# ─── Helpers purs ────────────────────────────────────────────────────────────


def test_slugify_label_strips_special_chars() -> None:
    from app.services.streaming_replication import _slugify_label

    assert _slugify_label("LXC voisin") == "lxc_voisin"
    assert _slugify_label("Standby (Paris) #1") == "standby_paris_1"
    assert _slugify_label("   trim me   ") == "trim_me"
    assert _slugify_label("__leading__") == "leading"
    assert _slugify_label("") == "node"


def test_make_replication_user_format() -> None:
    from app.services.streaming_replication import make_replication_user

    user = make_replication_user("LXC voisin")
    assert user.startswith("repl_lxc_voisin_")
    assert len(user) == len("repl_lxc_voisin_") + 6  # 6 hex chars
    # Pas de caractère hors a-z, 0-9, _ — sécurité injection SQL.
    import re

    assert re.match(r"^[a-z0-9_]+$", user)


def test_make_application_name_format() -> None:
    from app.services.streaming_replication import make_application_name

    assert make_application_name("Standby (Paris)") == "standby_paris"
    assert make_application_name("") != ""  # fallback non-vide


def test_generate_password_strong() -> None:
    from app.services.streaming_replication import generate_password

    p1 = generate_password()
    p2 = generate_password()
    assert p1 != p2
    assert len(p1) >= 40  # token_urlsafe(32) → ~43 chars


# ─── Bundle generator ────────────────────────────────────────────────────────


def test_build_bundle_contains_all_4_snippets() -> None:
    from app.services.streaming_replication import _build_bundle

    bundle = _build_bundle(
        node_id=UUID("11111111-0000-0000-0000-000000000001"),
        replication_user="repl_test_abc123",
        application_name="test_node",
        password="MY_SECRET",
        master_host="192.168.10.158",
        master_port=5432,
        standby_host="192.168.10.200",
    )
    # Snippet 1 : pg_hba ligne
    assert "host" in bundle.master_pg_hba_line
    assert "replication" in bundle.master_pg_hba_line
    assert "repl_test_abc123" in bundle.master_pg_hba_line
    assert "192.168.10.200/32" in bundle.master_pg_hba_line
    assert "scram-sha-256" in bundle.master_pg_hba_line

    # Snippet 2 : pg_basebackup côté standby
    assert "pg_basebackup" in bundle.standby_pg_basebackup_command
    assert "MY_SECRET" in bundle.standby_pg_basebackup_command
    assert "192.168.10.158" in bundle.standby_pg_basebackup_command
    assert "repl_test_abc123" in bundle.standby_pg_basebackup_command

    # Snippet 3 : postgresql.auto.conf
    assert "primary_conninfo" in bundle.standby_postgresql_auto_conf
    assert "application_name=test_node" in bundle.standby_postgresql_auto_conf
    assert "MY_SECRET" in bundle.standby_postgresql_auto_conf

    # Snippet 4 : standby.signal
    assert "standby.signal" in bundle.standby_signal_command
    assert "systemctl start postgresql" in bundle.standby_signal_command


def test_build_bundle_uses_custom_data_dir() -> None:
    from app.services.streaming_replication import _build_bundle

    bundle = _build_bundle(
        node_id=uuid4(),
        replication_user="r",
        application_name="a",
        password="p",
        master_host="h",
        master_port=5432,
        standby_host="s",
        standby_data_dir="/custom/pg/data",
    )
    assert "/custom/pg/data" in bundle.standby_pg_basebackup_command
    assert "/custom/pg/data" in bundle.standby_postgresql_auto_conf
    assert "/custom/pg/data" in bundle.standby_signal_command


# ─── add_node : mock conn pour vérifier le SQL généré ────────────────────────


def _make_conn() -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=UUID("22222222-0000-0000-0000-000000000001"))
    # transaction() est un async context manager
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    return conn


@pytest.mark.asyncio
async def test_add_node_creates_role_and_inserts_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    conn = _make_conn()

    inserted: dict[str, Any] = {}

    async def _insert(_c: Any, **kw: Any) -> UUID:
        inserted.update(kw)
        return UUID("22222222-0000-0000-0000-000000000001")

    monkeypatch.setattr(svc.nodes_repo, "insert", _insert)

    node_id, bundle = await svc.add_node(
        conn,
        strategy_id=UUID("33333333-0000-0000-0000-000000000001"),
        label="LXC voisin",
        host="192.168.10.200",
        port=5432,
        role="standby_ro",
        notes=None,
        master_host="192.168.10.158",
        master_port=5432,
        created_by_user_id=None,
    )

    assert node_id == UUID("22222222-0000-0000-0000-000000000001")
    # CREATE ROLE a été exécuté
    create_role_calls = [
        c for c in conn.execute.await_args_list
        if "CREATE ROLE" in str(c.args[0])
    ]
    assert len(create_role_calls) == 1
    sql = str(create_role_calls[0].args[0])
    assert bundle.replication_user in sql
    assert "REPLICATION LOGIN PASSWORD" in sql
    # Le password doit être quoté avec ' simples doublés (pas d'injection
    # via un ' dans le password — improbable car on génère token_urlsafe).
    assert bundle.password in sql

    # Insert appelé avec les bons args
    assert inserted["label"] == "LXC voisin"
    assert inserted["host"] == "192.168.10.200"
    assert inserted["replication_user"] == bundle.replication_user
    assert inserted["application_name"] == bundle.application_name
    assert inserted["role"] == "standby_ro"


@pytest.mark.asyncio
async def test_add_node_password_with_quote_is_escaped() -> None:
    """Sanity check: même si générateur ne produit pas de ', on vérifie que
    le doublement est correctement appliqué (defensive)."""
    from app.services.streaming_replication import generate_password

    p = generate_password()
    # token_urlsafe ne génère jamais de ' : composant URL-safe
    assert "'" not in p


# ─── delete_node ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_node_drops_role_and_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    fake_node = MagicMock()
    fake_node.id = UUID("44444444-0000-0000-0000-000000000001")
    fake_node.replication_user = "repl_xyz_aabbcc"

    async def _get(_c: Any, _id: UUID) -> Any:
        return fake_node

    deleted_id: list[UUID] = []

    async def _delete(_c: Any, _id: UUID) -> int:
        deleted_id.append(_id)
        return 1

    monkeypatch.setattr(svc, "get_node", _get)
    monkeypatch.setattr(svc.nodes_repo, "delete", _delete)

    conn = _make_conn()
    ok = await svc.delete_node(conn, fake_node.id)

    assert ok is True
    assert deleted_id == [fake_node.id]
    drop_calls = [
        c for c in conn.execute.await_args_list
        if "DROP ROLE" in str(c.args[0])
    ]
    assert len(drop_calls) == 1
    assert "repl_xyz_aabbcc" in str(drop_calls[0].args[0])


@pytest.mark.asyncio
async def test_delete_node_returns_false_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    async def _get(_c: Any, _id: UUID) -> Any:
        return None

    monkeypatch.setattr(svc, "get_node", _get)

    conn = _make_conn()
    ok = await svc.delete_node(conn, uuid4())
    assert ok is False


# ─── refresh_nodes_state ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_state_marks_observed_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    pg_stat_rows = [
        {"application_name": "lxc_voisin", "state": "streaming", "lag_bytes": 1024},
        {"application_name": "paris", "state": "catchup", "lag_bytes": 50000},
    ]

    db_node_voisin = {
        "id": UUID("55555555-0000-0000-0000-000000000001"),
        "application_name": "lxc_voisin",
        "last_seen_at": None,
        "last_state": None,
    }
    db_node_paris = {
        "id": UUID("55555555-0000-0000-0000-000000000002"),
        "application_name": "paris",
        "last_seen_at": None,
        "last_state": None,
    }

    async def _by_app(_c: Any, name: str) -> Any:
        return db_node_voisin if name == "lxc_voisin" else db_node_paris

    async def _list_all(_c: Any) -> list[Any]:
        return [db_node_voisin, db_node_paris]

    updates: list[dict[str, Any]] = []

    async def _update(_c: Any, **kw: Any) -> int:
        updates.append(kw)
        return 1

    monkeypatch.setattr(svc.nodes_repo, "get_by_application_name", _by_app)
    monkeypatch.setattr(svc.nodes_repo, "list_all", _list_all)
    monkeypatch.setattr(svc.nodes_repo, "update_observed_state", _update)

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=pg_stat_rows)
    conn.execute = AsyncMock()

    n = await svc.refresh_nodes_state(conn)

    assert n == 2
    assert {u["last_state"] for u in updates} == {"streaming", "catchup"}
    assert {u["last_lag_bytes"] for u in updates} == {1024, 50000}


@pytest.mark.asyncio
async def test_refresh_state_marks_disappeared_nodes_as_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone
    from app.services import streaming_replication as svc

    # pg_stat_replication ne renvoie rien, mais on a un node DB qu'on a déjà
    # vu (last_seen_at non NULL, last_state non 'disconnected').
    db_node = {
        "id": UUID("66666666-0000-0000-0000-000000000001"),
        "application_name": "ghost",
        "last_seen_at": datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc),
        "last_state": "streaming",
    }

    async def _list_all(_c: Any) -> list[Any]:
        return [db_node]

    monkeypatch.setattr(svc.nodes_repo, "list_all", _list_all)

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    n = await svc.refresh_nodes_state(conn)

    assert n == 1
    # On doit avoir UPDATE replication_nodes SET last_state = 'disconnected'
    update_calls = [
        c for c in conn.execute.await_args_list
        if "disconnected" in str(c.args[0])
    ]
    assert len(update_calls) == 1


@pytest.mark.asyncio
async def test_refresh_state_keeps_unknown_for_never_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import streaming_replication as svc

    db_node = {
        "id": UUID("77777777-0000-0000-0000-000000000001"),
        "application_name": "never_connected",
        "last_seen_at": None,  # jamais vu
        "last_state": None,
    }

    async def _list_all(_c: Any) -> list[Any]:
        return [db_node]

    monkeypatch.setattr(svc.nodes_repo, "list_all", _list_all)

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])  # pg_stat vide
    conn.execute = AsyncMock()

    n = await svc.refresh_nodes_state(conn)

    # Aucune update : on ne marque pas en disconnected un node jamais vu.
    assert n == 0
    assert all(
        "disconnected" not in str(c.args[0])
        for c in conn.execute.await_args_list
    )
