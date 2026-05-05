"""Format des messages MQTT pour la réplication inter-instances (LOT_21B).

Trois types de messages :
- `transaction` : modification d'une entité métier
- `replication_ack` : un peer a appliqué une transaction
- `node_hello` : annonce au démarrage / reconnexion (état de réplication par peer)

Format JSON commun :
    {
        "msg_id": "<uuid>",
        "type": "<type>",
        "emitter_id": "<instance>",
        "occurred_at": "<iso8601>",
        ... champs spécifiques
    }
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TransactionMessage:
    msg_id: str
    emitter_id: str
    seq: int
    entity_type: str
    entity_id: str
    operation: str  # 'upsert' | 'delete'
    payload: dict[str, Any]
    occurred_at: str

    type: str = "transaction"

    def to_json(self) -> bytes:
        return json.dumps({
            "msg_id": self.msg_id,
            "type": self.type,
            "emitter_id": self.emitter_id,
            "seq": self.seq,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "operation": self.operation,
            "payload": self.payload,
            "occurred_at": self.occurred_at,
        }, default=_json_default).encode("utf-8")


@dataclass(frozen=True)
class ReplicationAckMessage:
    msg_id: str
    emitter_id: str
    seq: int
    source_emitter: str
    source_seq: int
    occurred_at: str

    type: str = "replication_ack"

    def to_json(self) -> bytes:
        return json.dumps({
            "msg_id": self.msg_id,
            "type": self.type,
            "emitter_id": self.emitter_id,
            "seq": self.seq,
            "source_emitter": self.source_emitter,
            "source_seq": self.source_seq,
            "occurred_at": self.occurred_at,
        }).encode("utf-8")


@dataclass(frozen=True)
class NodeHelloMessage:
    msg_id: str
    emitter_id: str
    replication_state: dict[str, dict[str, int]]  # peer -> {last_applied_seq: N}
    occurred_at: str

    type: str = "node_hello"

    def to_json(self) -> bytes:
        return json.dumps({
            "msg_id": self.msg_id,
            "type": self.type,
            "emitter_id": self.emitter_id,
            "replication_state": self.replication_state,
            "occurred_at": self.occurred_at,
        }).encode("utf-8")


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def new_msg_id() -> str:
    return str(uuid.uuid4())


def _json_default(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    raise TypeError(f"non-serializable: {type(value).__name__}")


def parse_message(raw: bytes) -> dict[str, Any]:
    """Parse un message MQTT brut. Lève ValueError si format invalide."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("message must be a JSON object")
    if "type" not in data or "emitter_id" not in data:
        raise ValueError("message missing required fields type/emitter_id")
    return data


def topic_for_cluster(cluster_id: str) -> str:
    """Topic MQTT unique par cluster — `harpocrate/sync/<cluster_id>`."""
    return f"harpocrate/sync/{cluster_id}"
