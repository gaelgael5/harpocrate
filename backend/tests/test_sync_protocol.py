"""Tests format des messages MQTT de réplication (LOT_21B)."""
from __future__ import annotations

import base64
import json

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_transaction_message_round_trips() -> None:
    from app.services.sync_protocol import TransactionMessage, parse_message
    msg = TransactionMessage(
        msg_id="m1",
        emitter_id="node-a",
        seq=42,
        entity_type="secrets",
        entity_id="11111111-1111-1111-1111-111111111111",
        operation="upsert",
        payload={"id": "11111111-1111-1111-1111-111111111111", "name": "k"},
        occurred_at="2026-05-05T20:00:00+00:00",
    )
    raw = msg.to_json()
    parsed = parse_message(raw)
    assert parsed["type"] == "transaction"
    assert parsed["emitter_id"] == "node-a"
    assert parsed["seq"] == 42
    assert parsed["payload"]["name"] == "k"


def test_replication_ack_message_format() -> None:
    from app.services.sync_protocol import ReplicationAckMessage, parse_message
    ack = ReplicationAckMessage(
        msg_id="m2",
        emitter_id="node-b",
        seq=99,
        source_emitter="node-a",
        source_seq=42,
        occurred_at="2026-05-05T20:00:01+00:00",
    )
    parsed = parse_message(ack.to_json())
    assert parsed["type"] == "replication_ack"
    assert parsed["source_emitter"] == "node-a"
    assert parsed["source_seq"] == 42


def test_node_hello_message_format() -> None:
    from app.services.sync_protocol import NodeHelloMessage, parse_message
    hello = NodeHelloMessage(
        msg_id="m3",
        emitter_id="node-c",
        replication_state={"node-a": {"last_applied_seq": 42}},
        occurred_at="2026-05-05T20:00:00+00:00",
    )
    parsed = parse_message(hello.to_json())
    assert parsed["type"] == "node_hello"
    assert parsed["replication_state"]["node-a"]["last_applied_seq"] == 42


def test_parse_message_rejects_invalid_json() -> None:
    from app.services.sync_protocol import parse_message
    with pytest.raises(ValueError, match="invalid json"):
        parse_message(b"not-json{")


def test_parse_message_rejects_missing_required_fields() -> None:
    from app.services.sync_protocol import parse_message
    with pytest.raises(ValueError, match="required fields"):
        parse_message(json.dumps({"type": "transaction"}).encode())
    with pytest.raises(ValueError, match="required fields"):
        parse_message(json.dumps({"emitter_id": "x"}).encode())


def test_topic_for_cluster_isolates_clusters() -> None:
    from app.services.sync_protocol import topic_for_cluster
    assert topic_for_cluster("alpha") == "harpocrate/sync/alpha"
    assert topic_for_cluster("alpha") != topic_for_cluster("beta")


def test_transaction_serializes_uuid_and_datetime() -> None:
    """Le json default handler accepte UUID + datetime nativement."""
    import datetime
    import uuid

    from app.services.sync_protocol import TransactionMessage
    msg = TransactionMessage(
        msg_id="m4",
        emitter_id="node-d",
        seq=1,
        entity_type="wallets",
        entity_id="22222222-2222-2222-2222-222222222222",
        operation="upsert",
        payload={
            "id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
            "created_at": datetime.datetime(2026, 5, 5, tzinfo=datetime.UTC),
        },
        occurred_at="2026-05-05T20:00:00+00:00",
    )
    raw = msg.to_json()  # ne doit pas raise
    parsed = json.loads(raw.decode())
    assert parsed["payload"]["id"] == "22222222-2222-2222-2222-222222222222"
    assert parsed["payload"]["created_at"].startswith("2026-05-05")
