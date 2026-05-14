"""Consumer MQTT — applique les transactions reçues d'autres instances (LOT_21B).

Topic souscrit : `harpocrate/sync/<cluster_id>` (QoS 1, persistent session).

Comportement :
- Self-filtering : ignore ses propres messages (`emitter_id == nous`).
- Apply transaction : delegate à `app/services/sync_apply.apply_transaction()`
  qui SET LOCAL harpocrate.is_replication=true pour empêcher la réémission.
- Étagère : si `seq != last_applied + 1` pour ce peer, on shelve. Quand on
  reçoit le seq manquant, on déstacke en cascade.
- node_hello : log informatif (négociation de cursor déléguée à un futur lot).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import aiomqtt
import asyncpg

from app.core.logging import logger
from app.db.repositories import sync_replication as sync_repo
from app.services import sync_apply
from app.services import sync_protocol as proto

RECONNECT_DELAY_SECONDS = 5.0


class SyncConsumer:
    """Boucle réception MQTT + apply en arrière-plan."""

    def __init__(
        self,
        *,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str | None,
        mqtt_password: str | None,
        instance_id: str,
        cluster_id: str,
    ) -> None:
        self._host = mqtt_host
        self._port = mqtt_port
        self._username = mqtt_username or None
        self._password = mqtt_password or None
        self._instance_id = instance_id
        self._cluster_id = cluster_id
        self._topic = proto.topic_for_cluster(cluster_id)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @staticmethod
    async def _get_pool() -> asyncpg.Pool[asyncpg.Record]:
        from app.db.pool import get_pool

        return await get_pool()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="sync-consumer")
        logger.info("sync_consumer_started", cluster=self._cluster_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        logger.info("sync_consumer_stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    identifier=f"{self._instance_id}-sub",
                    clean_session=False,
                ) as client:
                    await client.subscribe(self._topic, qos=1)
                    logger.info(
                        "sync_consumer_connected",
                        host=self._host,
                        topic=self._topic,
                    )
                    async for message in client.messages:
                        if self._stop.is_set():
                            break
                        await self._handle_message_safe(bytes(message.payload))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("sync_consumer_error", error=str(exc))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=RECONNECT_DELAY_SECONDS,
                    )

    async def _handle_message_safe(self, raw: bytes) -> None:
        try:
            data = proto.parse_message(raw)
        except ValueError as exc:
            logger.warning("sync_consumer_parse_error", error=str(exc))
            return

        # Self-filtering — on ignore nos propres messages
        if data.get("emitter_id") == self._instance_id:
            return

        msg_type = data.get("type")
        try:
            if msg_type == "transaction":
                await self._handle_transaction(data)
            elif msg_type == "replication_ack":
                await self._handle_ack(data)
            elif msg_type == "node_hello":
                await self._handle_node_hello(data)
            else:
                logger.warning("sync_consumer_unknown_type", type=msg_type)
        except Exception as exc:
            logger.error(
                "sync_consumer_apply_failed",
                type=msg_type,
                emitter=data.get("emitter_id"),
                seq=data.get("seq"),
                error=str(exc),
            )

    async def _handle_transaction(self, data: dict[str, Any]) -> None:
        peer = str(data["emitter_id"])
        seq = int(data["seq"])

        async with (await self._get_pool()).acquire() as conn:
            state = await sync_repo.get_state_for_peer(conn, peer)
            last_applied = int(state["last_applied_seq"]) if state else 0

            if seq <= last_applied:
                logger.debug("sync_transaction_already_applied", peer=peer, seq=seq)
                return

            if seq != last_applied + 1:
                # Hors-ordre — on shelve
                await sync_repo.shelve_message(
                    conn,
                    source_emitter=peer,
                    source_seq=seq,
                    payload=data,
                )
                await sync_repo.upsert_received(
                    conn, peer=peer, last_received_seq=seq
                )
                logger.info(
                    "sync_transaction_shelved",
                    peer=peer,
                    seq=seq,
                    expected=last_applied + 1,
                )
                return

            await sync_apply.apply_transaction_in_tx(
                conn,
                instance_id=self._instance_id,
                peer_emitter=peer,
                peer_seq=seq,
                entity_type=str(data["entity_type"]),
                operation=str(data["operation"]),
                payload=data.get("payload") or {},
            )
            logger.debug("sync_transaction_applied", peer=peer, seq=seq)

            # Drain de l'étagère en cascade tant que le seq suivant est dispo
            await self._drain_shelf(conn, peer)

    async def _drain_shelf(
        self,
        conn: asyncpg.Connection[asyncpg.Record],
        peer: str,
    ) -> None:
        while True:
            state = await sync_repo.get_state_for_peer(conn, peer)
            if state is None:
                return
            next_seq = int(state["last_applied_seq"]) + 1
            row = await sync_repo.fetch_next_shelved(
                conn, source_emitter=peer, expected_seq=next_seq
            )
            if row is None:
                return
            data = row["payload"]
            if isinstance(data, str):
                import json
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    await sync_repo.remove_shelved(
                        conn, source_emitter=peer, source_seq=next_seq
                    )
                    continue
            await sync_apply.apply_transaction_in_tx(
                conn,
                instance_id=self._instance_id,
                peer_emitter=peer,
                peer_seq=next_seq,
                entity_type=str(data["entity_type"]),
                operation=str(data["operation"]),
                payload=data.get("payload") or {},
            )
            await sync_repo.remove_shelved(
                conn, source_emitter=peer, source_seq=next_seq
            )
            logger.info("sync_transaction_drained", peer=peer, seq=next_seq)

    async def _handle_ack(self, data: dict[str, Any]) -> None:
        # Simple comptabilité informationnelle. La vraie gestion d'ack
        # (last_acked_seq par peer) viendra avec un futur lot.
        logger.debug(
            "sync_ack_received",
            from_peer=data.get("emitter_id"),
            for_source=data.get("source_emitter"),
            source_seq=data.get("source_seq"),
        )

    async def _handle_node_hello(self, data: dict[str, Any]) -> None:
        # MVP : on logue. Négociation de cursor automatique = futur lot.
        logger.info(
            "sync_node_hello_received",
            from_peer=data.get("emitter_id"),
            their_state=data.get("replication_state"),
        )
