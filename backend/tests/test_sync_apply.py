"""Tests sync_apply — application des transactions reçues (LOT_21B)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=42)

    class _Tx:
        async def __aenter__(self) -> Any:
            return None

        async def __aexit__(self, *_a: Any) -> None:
            pass

    conn.transaction = MagicMock(return_value=_Tx())
    return conn


@pytest.mark.asyncio
async def test_apply_transaction_skips_unknown_entity_type() -> None:
    """Un entity_type hors whitelist est ignoré sans planter (forward-compat)."""
    from app.services.sync_apply import apply_transaction_in_tx

    conn = _conn()
    await apply_transaction_in_tx(
        conn,
        instance_id="me",
        peer_emitter="them",
        peer_seq=1,
        entity_type="unknown_table",
        operation="upsert",
        payload={"id": "x"},
    )
    # Aucun execute SQL hormis le check session — vérifier rien d'écrit
    conn.transaction.assert_not_called()


@pytest.mark.asyncio
async def test_apply_transaction_sets_replication_session_vars() -> None:
    """SET LOCAL is_replication=true + instance_id avant apply."""
    from app.services.sync_apply import apply_transaction_in_tx

    conn = _conn()
    await apply_transaction_in_tx(
        conn,
        instance_id="me-instance",
        peer_emitter="them",
        peer_seq=5,
        entity_type="secrets",
        operation="upsert",
        payload={"id": "11111111-1111-1111-1111-111111111111", "name": "k"},
    )

    # Vérifie que les SET LOCAL ont été émis
    sql_calls = [str(c.args[0]) for c in conn.execute.await_args_list]
    assert any("harpocrate.is_replication" in s for s in sql_calls)
    assert any("harpocrate.instance_id" in s for s in sql_calls)
    # DELETE puis INSERT
    assert any("DELETE FROM secrets" in s for s in sql_calls)
    assert any("INSERT INTO secrets" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_apply_transaction_delete_path() -> None:
    """Operation 'delete' → DELETE only + ack."""
    from app.services.sync_apply import apply_transaction_in_tx

    conn = _conn()
    await apply_transaction_in_tx(
        conn,
        instance_id="me",
        peer_emitter="them",
        peer_seq=7,
        entity_type="wallets",
        operation="delete",
        payload={"id": "22222222-2222-2222-2222-222222222222"},
    )

    sql_calls = [str(c.args[0]) for c in conn.execute.await_args_list]
    assert any("DELETE FROM wallets" in s for s in sql_calls)
    assert not any("INSERT INTO wallets" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_apply_transaction_skips_missing_id() -> None:
    """Un payload sans id ne fait rien (pas de DELETE incontrôlé)."""
    from app.services.sync_apply import apply_transaction_in_tx

    conn = _conn()
    await apply_transaction_in_tx(
        conn,
        instance_id="me",
        peer_emitter="them",
        peer_seq=3,
        entity_type="users",
        operation="upsert",
        payload={"email": "no-id@x"},
    )
    sql_calls = [str(c.args[0]) for c in conn.execute.await_args_list]
    # Pas de DELETE/INSERT sur la table cible — l'ack dans sync_log peut être émis
    assert not any("FROM users" in s for s in sql_calls)
    assert not any("INSERT INTO users" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_apply_transaction_unknown_operation_ignored() -> None:
    """Operation inconnue → log + return, pas d'ack ni d'apply."""
    from app.services.sync_apply import apply_transaction_in_tx

    conn = _conn()
    await apply_transaction_in_tx(
        conn,
        instance_id="me",
        peer_emitter="them",
        peer_seq=4,
        entity_type="secrets",
        operation="weird_op",
        payload={"id": "x"},
    )
    sql_calls = [str(c.args[0]) for c in conn.execute.await_args_list]
    # Les SET LOCAL sont émis (entrée dans la transaction) mais pas de DELETE/INSERT
    assert not any("DELETE FROM secrets" in s for s in sql_calls)
