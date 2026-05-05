"""Publisher MQTT — diffuse les transactions locales aux autres instances (LOT_21B).

Lit les nouvelles entrées de `sync_log` (cursor de push) et les pousse sur le
topic `harpocrate/sync/<cluster_id>` du broker MQTT. QoS 1 + clean_session=False
pour profiter de la persistance broker en cas de déconnexion brève.

Le cursor est avancé après publication réussie. En cas de crash, on re-publie
les messages non acquittés (idempotence garantie côté consumer via msg_id).
"""

from __future__ import annotations

import asyncio
import contextlib

import aiomqtt
import asyncpg

from app.core.logging import logger
from app.db.repositories import sync_replication as sync_repo
from app.services import sync_protocol as proto

BATCH_SIZE = 100
IDLE_POLL_SECONDS = 1.0
RECONNECT_DELAY_SECONDS = 5.0


class SyncPublisher:
    """Pompe sync_log → MQTT en arrière-plan."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool[asyncpg.Record],
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str | None,
        mqtt_password: str | None,
        instance_id: str,
        cluster_id: str,
    ) -> None:
        self._pool = pool
        self._host = mqtt_host
        self._port = mqtt_port
        self._username = mqtt_username or None
        self._password = mqtt_password or None
        self._instance_id = instance_id
        self._cluster_id = cluster_id
        self._topic = proto.topic_for_cluster(cluster_id)
        self._cursor = 0
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        async with self._pool.acquire() as conn:
            self._cursor = await sync_repo.get_push_cursor(conn)
        self._task = asyncio.create_task(self._loop(), name="sync-publisher")
        logger.info(
            "sync_publisher_started",
            cursor=self._cursor,
            cluster=self._cluster_id,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        logger.info("sync_publisher_stopped")

    async def reset_cursor(self, new_cursor: int) -> None:
        """Reset manuel du cursor (admin ou négociation node_hello)."""
        async with self._pool.acquire() as conn:
            await sync_repo.set_push_cursor(conn, new_cursor)
        self._cursor = new_cursor
        logger.info("sync_publisher_cursor_reset", new_cursor=new_cursor)

    @property
    def cursor(self) -> int:
        return self._cursor

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    identifier=f"{self._instance_id}-pub",
                    clean_session=False,
                ) as client:
                    logger.info(
                        "sync_publisher_connected",
                        host=self._host,
                        cluster=self._cluster_id,
                    )
                    await self._publish_node_hello(client)
                    while not self._stop.is_set():
                        published = await self._publish_batch(client)
                        if published == 0:
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(
                                    self._stop.wait(),
                                    timeout=IDLE_POLL_SECONDS,
                                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("sync_publisher_error", error=str(exc))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=RECONNECT_DELAY_SECONDS,
                    )

    async def _publish_batch(self, client: aiomqtt.Client) -> int:
        async with self._pool.acquire() as conn:
            rows = await sync_repo.fetch_outbound_batch(
                conn,
                emitter_id=self._instance_id,
                cursor=self._cursor,
                limit=BATCH_SIZE,
            )
        if not rows:
            return 0
        for row in rows:
            payload = self._row_to_message_bytes(row)
            await client.publish(self._topic, payload=payload, qos=1)
            self._cursor = int(row["seq"])
        async with self._pool.acquire() as conn:
            await sync_repo.set_push_cursor(conn, self._cursor)
        logger.debug(
            "sync_publisher_batch",
            count=len(rows),
            cursor=self._cursor,
        )
        return len(rows)

    async def _publish_node_hello(self, client: aiomqtt.Client) -> None:
        """Annonce notre état de réplication courant (filet de sécurité au démarrage)."""
        async with self._pool.acquire() as conn:
            states = await sync_repo.list_states(conn)
        replication_state = {
            row["peer_emitter"]: {
                "last_applied_seq": int(row["last_applied_seq"]),
            }
            for row in states
        }
        msg = proto.NodeHelloMessage(
            msg_id=proto.new_msg_id(),
            emitter_id=self._instance_id,
            replication_state=replication_state,
            occurred_at=proto.now_iso(),
        )
        await client.publish(self._topic, payload=msg.to_json(), qos=1)
        logger.info("sync_node_hello_emitted", peers=list(replication_state.keys()))

    def _row_to_message_bytes(self, row: asyncpg.Record) -> bytes:
        if row["type"] == "transaction":
            payload = row["payload"]
            if isinstance(payload, str):
                import json
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {"raw": payload}
            return proto.TransactionMessage(
                msg_id=proto.new_msg_id(),
                emitter_id=self._instance_id,
                seq=int(row["seq"]),
                entity_type=str(row["entity_type"]),
                entity_id=str(row["entity_id"]),
                operation=str(row["operation"]),
                payload=payload if isinstance(payload, dict) else {},
                occurred_at=row["occurred_at"].isoformat(),
            ).to_json()
        # replication_ack
        return proto.ReplicationAckMessage(
            msg_id=proto.new_msg_id(),
            emitter_id=self._instance_id,
            seq=int(row["seq"]),
            source_emitter=str(row["source_emitter"]),
            source_seq=int(row["source_seq"]),
            occurred_at=row["occurred_at"].isoformat(),
        ).to_json()
