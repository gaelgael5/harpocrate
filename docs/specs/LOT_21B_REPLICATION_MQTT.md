# Lot 21B — Réplication applicative multi-instances via MQTT

> **Prérequis** : Lots 00-21A.
> **Statut** : Implémentation — réplication applicative E2E préservée.

## Objectif

Permettre à plusieurs instances Harpocrate de se répliquer mutuellement via un broker MQTT dédié. Chaque instance publie ses modifications sous forme de transactions numérotées. Les autres instances consomment, appliquent, et acquittent. Le protocole est **auto-réparant** : au démarrage ou redémarrage, les instances s'annoncent et négocient automatiquement les messages manquants.

**Contrainte fondamentale** : E2E préservé. Les blobs chiffrés sont répliqués tels quels — aucune instance ne déchiffre pour répliquer.

---

## Périmètre

### Inclus

- Table `sync_log` partitionnée par jour (BIGSERIAL, transactions + acks)
- Table `sync_shelf` (messages hors-ordre en attente)
- Table `sync_replication_state` (état de réplication par peer)
- Triggers sur toutes les tables métier → INSERT dans `sync_log`
- Publisher MQTT (background task asyncio) avec cursor de push
- Consumer MQTT (background task asyncio) avec étagère par source
- Protocole de handshake au démarrage (`node_hello`)
- Négociation automatique du cursor de push entre peers
- Self-filtering : chaque instance ignore ses propres messages
- Marquage `is_replication=true` pour les transactions issues d'une réplication
- Ack vide avec `source_emitter` + `source_seq` dans la séquence locale
- UI `/admin/replication/sync-state` : état de chaque peer, lag, cursor
- UI : reset manuel du cursor de push local
- Partitionnement `sync_log` par jour + création automatique des partitions
- Purge configurable via `HARPOCRATE_SYNC_LOG_RETENTION_DAYS`
- Docker Compose avec service MQTT dédié (`docker-compose.cluster.yml`)
- QoS 1 + persistent session MQTT, TTL messages configurable (défaut 30min)

### Exclus

- Pas de full sync à chaud — rejoindre le cluster = restore d'un backup
- Pas de résolution de conflits complexe (generation_version gagne)
- Pas de chiffrement E2E des payloads MQTT (les blobs sont déjà chiffrés)
- Pas de SDK npm ni CLI (lots futurs)

---

## Partie 1 — Modèle de données

### `sync_log` — journal partitionné

```sql
-- migrations/012_sync_log.sql

-- Table partitionnée par jour
CREATE TABLE sync_log (
    seq             BIGSERIAL,
    emitter_id      TEXT NOT NULL,
    type            TEXT NOT NULL,

    -- Pour type = 'transaction'
    entity_type     TEXT,
    entity_id       UUID,
    operation       TEXT CHECK (operation IN ('upsert', 'delete')),
    payload         JSONB,
    is_replication  BOOLEAN NOT NULL DEFAULT FALSE,

    -- Pour type = 'replication_ack'
    source_emitter  TEXT,
    source_seq      BIGINT,

    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT sync_log_type_check
        CHECK (type IN ('transaction', 'replication_ack')),
    CONSTRAINT sync_log_transaction_check CHECK (
        type != 'transaction'
        OR (entity_type IS NOT NULL AND entity_id IS NOT NULL AND operation IS NOT NULL)
    ),
    CONSTRAINT sync_log_ack_check CHECK (
        type != 'replication_ack'
        OR (source_emitter IS NOT NULL AND source_seq IS NOT NULL)
    )
) PARTITION BY RANGE (occurred_at);

-- Partition initiale (aujourd'hui)
CREATE TABLE sync_log_default PARTITION OF sync_log DEFAULT;

-- Index sur la partition mère (hérités par toutes les partitions)
CREATE INDEX idx_sync_log_emitter_seq ON sync_log(emitter_id, seq);
CREATE INDEX idx_sync_log_acks
    ON sync_log(source_emitter, source_seq)
    WHERE type = 'replication_ack';
CREATE INDEX idx_sync_log_occurred_at ON sync_log(occurred_at DESC);

-- Cursor de push dans system_metadata
INSERT INTO system_metadata (key, value) VALUES
    ('sync_push_cursor', '0'),
    ('sync_enabled', 'false');
```

### `sync_shelf` — étagère persistante

```sql
CREATE TABLE sync_shelf (
    source_emitter  TEXT NOT NULL,
    source_seq      BIGINT NOT NULL,
    payload         JSONB NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_emitter, source_seq)
);
```

### `sync_replication_state` — état de réplication par peer

```sql
CREATE TABLE sync_replication_state (
    peer_emitter        TEXT NOT NULL PRIMARY KEY,
    last_applied_seq    BIGINT NOT NULL DEFAULT 0,
    last_acked_seq      BIGINT NOT NULL DEFAULT 0,
    last_received_seq   BIGINT NOT NULL DEFAULT 0,
    last_seen_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('synced', 'lagging', 'unknown', 'stale'))
);
```

---

## Partie 2 — Triggers sur les tables métier

Chaque modification sur les tables métier insère une ligne dans `sync_log` dans la **même transaction**.

```sql
-- Fonction générique
CREATE OR REPLACE FUNCTION sync_log_trigger()
RETURNS TRIGGER AS $$
DECLARE
    v_operation TEXT;
    v_payload JSONB;
    v_emitter TEXT;
BEGIN
    -- Récupérer l'emitter depuis system_metadata
    SELECT value INTO v_emitter
    FROM system_metadata WHERE key = 'instance_id';

    -- Déterminer l'opération
    IF TG_OP = 'DELETE' THEN
        v_operation := 'delete';
        v_payload := jsonb_build_object('id', OLD.id);
    ELSE
        v_operation := 'upsert';
        v_payload := to_jsonb(NEW);
    END IF;

    -- Ne pas insérer si sync désactivé
    IF NOT EXISTS (
        SELECT 1 FROM system_metadata
        WHERE key = 'sync_enabled' AND value = 'true'
    ) THEN
        RETURN NEW;
    END IF;

    INSERT INTO sync_log (
        emitter_id, type, entity_type, entity_id,
        operation, payload, is_replication
    ) VALUES (
        v_emitter,
        'transaction',
        TG_TABLE_NAME,
        CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END,
        v_operation,
        v_payload,
        -- Marquer si issu d'une réplication (session variable)
        COALESCE(current_setting('harpocrate.is_replication', true)::boolean, false)
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Application sur toutes les tables métier
CREATE TRIGGER trg_sync_secrets
    AFTER INSERT OR UPDATE OR DELETE ON secrets
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

CREATE TRIGGER trg_sync_wallets
    AFTER INSERT OR UPDATE OR DELETE ON wallets
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

CREATE TRIGGER trg_sync_users
    AFTER INSERT OR UPDATE OR DELETE ON users
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

CREATE TRIGGER trg_sync_wallet_grants
    AFTER INSERT OR UPDATE OR DELETE ON wallet_grants
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

CREATE TRIGGER trg_sync_secret_types
    AFTER INSERT OR UPDATE OR DELETE ON secret_types
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();

CREATE TRIGGER trg_sync_secret_schemas
    AFTER INSERT OR UPDATE OR DELETE ON secret_schemas
    FOR EACH ROW EXECUTE FUNCTION sync_log_trigger();
```

### Marquage des transactions de réplication

Quand le consumer applique une transaction reçue, il utilise une session variable Postgres pour marquer les triggers :

```python
async def apply_transaction(conn, transaction: dict) -> None:
    """Applique une transaction reçue d'un peer."""
    async with conn.transaction():
        # Marquer la session : les triggers sauront que c'est une réplication
        await conn.execute(
            "SET LOCAL harpocrate.is_replication = true"
        )

        # Appliquer la modification
        await _apply_entity(conn, transaction)

        # Insérer l'ack dans sync_log (dans la même transaction)
        await conn.execute("""
            INSERT INTO sync_log (
                emitter_id, type, source_emitter, source_seq, is_replication
            ) VALUES (
                current_setting('harpocrate.instance_id'),
                'replication_ack',
                $1, $2, true
            )
        """, transaction["emitter_id"], transaction["seq"])

        # Mettre à jour l'état de réplication
        await conn.execute("""
            INSERT INTO sync_replication_state
                (peer_emitter, last_applied_seq, last_received_seq, last_seen_at, status)
            VALUES ($1, $2, $2, NOW(), 'synced')
            ON CONFLICT (peer_emitter) DO UPDATE
            SET last_applied_seq = GREATEST(
                    sync_replication_state.last_applied_seq, $2
                ),
                last_received_seq = GREATEST(
                    sync_replication_state.last_received_seq, $2
                ),
                last_seen_at = NOW(),
                status = 'synced'
        """, transaction["emitter_id"], transaction["seq"])
```

---

## Partie 3 — Format des messages MQTT

### Topic unique

```
harpocrate/sync/{cluster_id}
```

`cluster_id` configuré via `HARPOCRATE_SYNC_CLUSTER_ID`. Permet d'isoler plusieurs clusters sur le même broker.

### Message `transaction`

```json
{
  "msg_id": "uuid",
  "type": "transaction",
  "emitter_id": "instance-a",
  "seq": 145,
  "entity_type": "secret",
  "entity_id": "uuid",
  "operation": "upsert",
  "payload": {
    "id": "uuid",
    "wallet_id": "uuid",
    "name": "anthropic_api_key",
    "encrypted_value": "<base64>",
    "tags": ["prod"],
    "type_uuid": null,
    "schema_version_uuid": null,
    "generation_version": 3,
    "updated_at": "2026-05-04T14:23:00Z"
  },
  "occurred_at": "2026-05-04T14:23:00Z"
}
```

### Message `replication_ack`

```json
{
  "msg_id": "uuid",
  "type": "replication_ack",
  "emitter_id": "instance-b",
  "seq": 89,
  "source_emitter": "instance-a",
  "source_seq": 145,
  "occurred_at": "2026-05-04T14:23:01Z"
}
```

### Message `node_hello`

```json
{
  "msg_id": "uuid",
  "type": "node_hello",
  "emitter_id": "instance-b",
  "replication_state": {
    "instance-a": {
      "last_applied_seq": 145
    },
    "instance-c": {
      "last_applied_seq": 89
    }
  },
  "occurred_at": "2026-05-04T14:23:00Z"
}
```

---

## Partie 4 — Publisher MQTT

```python
# app/core/sync_publisher.py

import asyncio
import json
import logging
from typing import Optional

import asyncpg
from aiomqtt import Client as MQTTClient

logger = logging.getLogger("harpocrate.sync_publisher")

BATCH_SIZE = 100  # max messages par cycle


class SyncPublisher:
    """
    Lit les entrées non-publiées de sync_log et les publie sur MQTT.
    Maintient un cursor de push (seq du dernier message publié).
    """

    def __init__(self, pool: asyncpg.Pool, mqtt_config: dict, instance_id: str, cluster_id: str):
        self._pool = pool
        self._mqtt_config = mqtt_config
        self._instance_id = instance_id
        self._cluster_id = cluster_id
        self._topic = f"harpocrate/sync/{cluster_id}"
        self._cursor: int = 0
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        # Lire le cursor depuis system_metadata
        async with self._pool.acquire() as conn:
            self._cursor = await conn.fetchval(
                "SELECT value::bigint FROM system_metadata WHERE key = 'sync_push_cursor'"
            ) or 0

        self._task = asyncio.create_task(self._publish_loop())
        logger.info("sync_publisher_started", cursor=self._cursor, instance=self._instance_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def reset_cursor(self, new_cursor: int) -> None:
        """Reset manuel du cursor (admin ou négociation automatique)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE system_metadata SET value = $1 WHERE key = 'sync_push_cursor'",
                str(new_cursor)
            )
        self._cursor = new_cursor
        logger.info(
            "sync_push_cursor_reset",
            new_cursor=new_cursor,
            instance=self._instance_id
        )

    async def _publish_loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with MQTTClient(
                    hostname=self._mqtt_config["host"],
                    port=self._mqtt_config["port"],
                    username=self._mqtt_config["username"],
                    password=self._mqtt_config["password"],
                    client_id=f"{self._instance_id}-publisher",
                    clean_session=False,  # persistent session
                ) as mqtt:
                    logger.info("sync_publisher_connected", instance=self._instance_id)

                    while not self._stop.is_set():
                        published = await self._publish_batch(mqtt)
                        if published == 0:
                            # Pas de nouveaux messages, attendre
                            try:
                                await asyncio.wait_for(
                                    self._stop.wait(), timeout=1.0
                                )
                            except asyncio.TimeoutError:
                                pass

            except Exception as e:
                logger.error(
                    "sync_publisher_error",
                    error=str(e),
                    instance=self._instance_id
                )
                await asyncio.sleep(5)

    async def _publish_batch(self, mqtt: MQTTClient) -> int:
        """Publie un batch de messages depuis le cursor courant. Retourne le nombre publié."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT seq, type, entity_type, entity_id, operation,
                       payload, source_emitter, source_seq, occurred_at
                FROM sync_log
                WHERE emitter_id = $1
                  AND seq > $2
                ORDER BY seq ASC
                LIMIT $3
            """, self._instance_id, self._cursor, BATCH_SIZE)

        if not rows:
            return 0

        for row in rows:
            message = self._build_message(row)
            await mqtt.publish(
                self._topic,
                payload=json.dumps(message).encode(),
                qos=1,
                retain=False,
            )
            self._cursor = row["seq"]

        # Persister le cursor
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE system_metadata SET value = $1 WHERE key = 'sync_push_cursor'",
                str(self._cursor)
            )

        logger.debug(
            "sync_published_batch",
            count=len(rows),
            cursor=self._cursor,
            instance=self._instance_id
        )
        return len(rows)

    def _build_message(self, row: asyncpg.Record) -> dict:
        import uuid
        base = {
            "msg_id": str(uuid.uuid4()),
            "type": row["type"],
            "emitter_id": self._instance_id,
            "seq": row["seq"],
            "occurred_at": row["occurred_at"].isoformat(),
        }
        if row["type"] == "transaction":
            base.update({
                "entity_type": row["entity_type"],
                "entity_id": str(row["entity_id"]),
                "operation": row["operation"],
                "payload": row["payload"],
            })
        elif row["type"] == "replication_ack":
            base.update({
                "source_emitter": row["source_emitter"],
                "source_seq": row["source_seq"],
            })
        return base
```

---

## Partie 5 — Consumer MQTT avec étagère

```python
# app/core/sync_consumer.py

import asyncio
import json
import logging
from collections import defaultdict
from typing import Optional

import asyncpg
from aiomqtt import Client as MQTTClient

logger = logging.getLogger("harpocrate.sync_consumer")

SHELF_TIMEOUT_SECONDS = 300  # 5 minutes avant de considérer un gap irréparable


class SyncConsumer:
    """
    Consomme les messages MQTT du cluster.
    - Ignore ses propres messages (self-filtering)
    - Gère les messages hors-ordre via étagère persistante
    - Gère le protocole node_hello
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        mqtt_config: dict,
        publisher: "SyncPublisher",
        instance_id: str,
        cluster_id: str,
    ):
        self._pool = pool
        self._mqtt_config = mqtt_config
        self._publisher = publisher
        self._instance_id = instance_id
        self._cluster_id = cluster_id
        self._topic = f"harpocrate/sync/{cluster_id}"
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        # next_expected[emitter_id] = prochain seq attendu de cet emitter
        self._next_expected: dict[str, int] = {}

    async def start(self) -> None:
        # Reconstituer next_expected depuis sync_log et sync_shelf
        await self._restore_state()
        self._task = asyncio.create_task(self._consume_loop())
        logger.info("sync_consumer_started", instance=self._instance_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _restore_state(self) -> None:
        """Reconstitue l'état au démarrage depuis la DB."""
        async with self._pool.acquire() as conn:
            # Lire le dernier seq appliqué pour chaque peer
            rows = await conn.fetch(
                "SELECT peer_emitter, last_applied_seq FROM sync_replication_state"
            )
            for row in rows:
                self._next_expected[row["peer_emitter"]] = row["last_applied_seq"] + 1

            # Recharger l'étagère en RAM
            shelf_rows = await conn.fetch(
                "SELECT source_emitter, source_seq, payload FROM sync_shelf"
            )
            self._shelf: dict[str, dict[int, dict]] = defaultdict(dict)
            for row in shelf_rows:
                self._shelf[row["source_emitter"]][row["source_seq"]] = row["payload"]

    async def _consume_loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with MQTTClient(
                    hostname=self._mqtt_config["host"],
                    port=self._mqtt_config["port"],
                    username=self._mqtt_config["username"],
                    password=self._mqtt_config["password"],
                    client_id=f"{self._instance_id}-consumer",
                    clean_session=False,  # persistent session
                ) as mqtt:
                    await mqtt.subscribe(self._topic, qos=1)
                    logger.info("sync_consumer_subscribed", topic=self._topic)

                    # Publier node_hello au démarrage
                    await self._publish_hello(mqtt)

                    async for message in mqtt.messages:
                        if self._stop.is_set():
                            break
                        try:
                            data = json.loads(message.payload)
                            await self._handle_message(data, mqtt)
                        except Exception as e:
                            logger.error(
                                "sync_message_processing_error",
                                error=str(e),
                                instance=self._instance_id
                            )

            except Exception as e:
                logger.error(
                    "sync_consumer_error",
                    error=str(e),
                    instance=self._instance_id
                )
                await asyncio.sleep(5)

    async def _publish_hello(self, mqtt: MQTTClient) -> None:
        """Annonce ce nœud avec son état de réplication."""
        import uuid

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT peer_emitter, last_applied_seq FROM sync_replication_state"
            )

        replication_state = {
            row["peer_emitter"]: {"last_applied_seq": row["last_applied_seq"]}
            for row in rows
        }

        hello = {
            "msg_id": str(uuid.uuid4()),
            "type": "node_hello",
            "emitter_id": self._instance_id,
            "replication_state": replication_state,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

        await mqtt.publish(
            self._topic,
            payload=json.dumps(hello).encode(),
            qos=1,
        )
        logger.info(
            "sync_hello_published",
            state=replication_state,
            instance=self._instance_id
        )

    async def _handle_message(self, data: dict, mqtt: MQTTClient) -> None:
        emitter = data.get("emitter_id")

        # Self-filtering : ignorer ses propres messages
        if emitter == self._instance_id:
            return

        msg_type = data.get("type")

        if msg_type == "node_hello":
            await self._handle_hello(data)
        elif msg_type == "transaction":
            await self._handle_transaction(data)
        elif msg_type == "replication_ack":
            await self._handle_ack(data)

    async def _handle_hello(self, data: dict) -> None:
        """
        Un peer s'annonce avec son état de réplication.
        Vérifier si notre cursor de push couvre ses besoins.
        """
        peer_id = data["emitter_id"]
        peer_state = data.get("replication_state", {})

        logger.info(
            "sync_hello_received",
            from_peer=peer_id,
            peer_state=peer_state,
            instance=self._instance_id
        )

        # Mettre à jour last_seen_at
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sync_replication_state
                    (peer_emitter, last_seen_at, status)
                VALUES ($1, NOW(), 'unknown')
                ON CONFLICT (peer_emitter) DO UPDATE
                SET last_seen_at = NOW()
            """, peer_id)

        # Vérifier si ce peer a besoin de messages qu'on a déjà publiés
        our_state = peer_state.get(self._instance_id, {})
        peer_last_applied = our_state.get("last_applied_seq", 0)

        if peer_last_applied < self._publisher._cursor:
            # Le peer a besoin de messages depuis peer_last_applied
            # Vérifier si ces messages sont encore dans sync_log
            async with self._pool.acquire() as conn:
                oldest_available = await conn.fetchval(
                    "SELECT MIN(seq) FROM sync_log WHERE emitter_id = $1",
                    self._instance_id
                )

            if oldest_available and oldest_available <= peer_last_applied + 1:
                # On a les messages → reculer le cursor de push
                logger.info(
                    "sync_cursor_reset_for_peer",
                    peer=peer_id,
                    from_cursor=self._publisher._cursor,
                    to_cursor=peer_last_applied,
                    instance=self._instance_id
                )
                await self._publisher.reset_cursor(peer_last_applied)
            else:
                # Messages purgés → le peer doit faire un restore
                logger.warning(
                    "sync_peer_needs_restore",
                    peer=peer_id,
                    peer_last_applied=peer_last_applied,
                    oldest_available=oldest_available,
                    instance=self._instance_id
                )

    async def _handle_transaction(self, data: dict) -> None:
        """Traite une transaction reçue avec gestion de l'étagère."""
        emitter = data["emitter_id"]
        seq = data["seq"]

        # Mettre à jour last_received_seq
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sync_replication_state
                    (peer_emitter, last_received_seq, last_seen_at, status)
                VALUES ($1, $2, NOW(), 'synced')
                ON CONFLICT (peer_emitter) DO UPDATE
                SET last_received_seq = GREATEST(
                        sync_replication_state.last_received_seq, $2
                    ),
                    last_seen_at = NOW()
            """, emitter, seq)

        next_expected = self._next_expected.get(emitter, 1)

        if seq == next_expected:
            # Message dans l'ordre → appliquer directement
            await self._apply_and_drain_shelf(emitter, seq, data)

        elif seq > next_expected:
            # Message hors-ordre → étagère
            logger.debug(
                "sync_message_shelved",
                emitter=emitter,
                seq=seq,
                expected=next_expected,
                instance=self._instance_id
            )
            await self._put_on_shelf(emitter, seq, data)

        else:
            # seq < next_expected → doublon (QoS 1 peut retransmettre) → ignorer
            logger.debug(
                "sync_duplicate_ignored",
                emitter=emitter,
                seq=seq,
                instance=self._instance_id
            )

    async def _apply_and_drain_shelf(
        self, emitter: str, seq: int, data: dict
    ) -> None:
        """Applique un message puis vide l'étagère tant que possible."""
        await self._apply_transaction(data)
        self._next_expected[emitter] = seq + 1

        # Vider l'étagère
        while True:
            next_seq = self._next_expected[emitter]
            shelf_data = self._shelf.get(emitter, {}).pop(next_seq, None)
            if shelf_data is None:
                break

            await self._apply_transaction(shelf_data)
            self._next_expected[emitter] = next_seq + 1

            # Supprimer de la DB
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM sync_shelf WHERE source_emitter = $1 AND source_seq = $2",
                    emitter, next_seq
                )

    async def _put_on_shelf(self, emitter: str, seq: int, data: dict) -> None:
        """Persiste un message hors-ordre sur l'étagère."""
        if emitter not in self._shelf:
            self._shelf[emitter] = {}
        self._shelf[emitter][seq] = data

        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sync_shelf (source_emitter, source_seq, payload)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
            """, emitter, seq, json.dumps(data))

    async def _apply_transaction(self, data: dict) -> None:
        """Applique une transaction dans Postgres."""
        async with self._pool.acquire() as conn:
            await apply_transaction(conn, data)

    async def _handle_ack(self, data: dict) -> None:
        """Un peer a ackté une de nos transactions."""
        peer_id = data["emitter_id"]
        source_emitter = data["source_emitter"]
        source_seq = data["source_seq"]

        if source_emitter != self._instance_id:
            return  # Ack pour une autre instance

        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sync_replication_state
                    (peer_emitter, last_acked_seq, last_seen_at, status)
                VALUES ($1, $2, NOW(), 'synced')
                ON CONFLICT (peer_emitter) DO UPDATE
                SET last_acked_seq = GREATEST(
                        sync_replication_state.last_acked_seq, $2
                    ),
                    last_seen_at = NOW(),
                    status = 'synced'
            """, peer_id, source_seq)
```

---

## Partie 6 — Résolution de conflits

Quand deux instances modifient le même secret simultanément, on utilise `generation_version` (lot 06) :

```python
async def apply_entity(conn: asyncpg.Connection, data: dict) -> None:
    """Applique un upsert avec résolution de conflit."""
    entity_type = data["entity_type"]
    operation = data["operation"]
    payload = data["payload"]

    if operation == "delete":
        await _apply_delete(conn, entity_type, payload)
        return

    if entity_type == "secret":
        # Résolution de conflit : generation_version gagne
        await conn.execute("""
            INSERT INTO secrets (id, wallet_id, name, encrypted_value,
                                 generation_version, updated_at, ...)
            VALUES ($1, $2, $3, $4, $5, $6, ...)
            ON CONFLICT (id) DO UPDATE
            SET encrypted_value     = EXCLUDED.encrypted_value,
                generation_version  = EXCLUDED.generation_version,
                updated_at          = EXCLUDED.updated_at
            WHERE EXCLUDED.generation_version > secrets.generation_version
              OR (
                EXCLUDED.generation_version = secrets.generation_version
                AND EXCLUDED.updated_at > secrets.updated_at
              )
        """, ...)

    elif entity_type in ("wallet", "user", "wallet_grant", "secret_type", "secret_schema"):
        # Upsert standard : last updated_at gagne
        await _upsert_generic(conn, entity_type, payload)
```

---

## Partie 7 — Partitionnement et purge

### Création automatique des partitions

```python
# app/core/sync_partition_manager.py

import asyncpg
from datetime import date, timedelta


async def ensure_partitions(conn: asyncpg.Connection, days_ahead: int = 7) -> None:
    """Crée les partitions futures si elles n'existent pas."""
    today = date.today()

    for i in range(days_ahead):
        partition_date = today + timedelta(days=i)
        partition_name = f"sync_log_{partition_date.strftime('%Y_%m_%d')}"
        next_date = partition_date + timedelta(days=1)

        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {partition_name}
            PARTITION OF sync_log
            FOR VALUES FROM ('{partition_date}') TO ('{next_date}')
        """)


async def purge_old_partitions(
    conn: asyncpg.Connection,
    retention_days: int,
) -> list[str]:
    """Supprime les partitions plus vieilles que retention_days."""
    cutoff = date.today() - timedelta(days=retention_days)
    dropped = []

    # Lister les partitions existantes
    rows = await conn.fetch("""
        SELECT tablename FROM pg_tables
        WHERE tablename LIKE 'sync_log_%'
          AND schemaname = 'public'
    """)

    for row in rows:
        name = row["tablename"]
        # Parser la date depuis le nom (sync_log_2026_05_04)
        try:
            parts = name.split("_")
            partition_date = date(int(parts[2]), int(parts[3]), int(parts[4]))
            if partition_date < cutoff:
                await conn.execute(f"DROP TABLE IF EXISTS {name}")
                dropped.append(name)
        except (ValueError, IndexError):
            pass  # sync_log_default ou autre → ignorer

    return dropped
```

Planifié via la background task existante (lot 14 scheduler) :

```python
# Dans le tick quotidien du scheduler
await ensure_partitions(conn, days_ahead=7)
purged = await purge_old_partitions(conn, retention_days=settings.sync_log_retention_days)
if purged:
    logger.info("sync_log_partitions_purged", partitions=purged)
```

---

## Partie 8 — Docker Compose

```yaml
# docker-compose.cluster.yml
# Usage: docker compose -f docker-compose.yml \
#                       -f docker-compose.patroni.yml \
#                       -f docker-compose.cluster.yml up

services:
  harpocrate:
    environment:
      HARPOCRATE_SYNC_ENABLED: "true"
      HARPOCRATE_SYNC_CLUSTER_ID: "harpocrate-prod"
      HARPOCRATE_MQTT_HOST: "mqtt"
      HARPOCRATE_MQTT_PORT: "1883"
      HARPOCRATE_MQTT_USERNAME: "harpocrate"
      HARPOCRATE_MQTT_PASSWORD: "${MQTT_PASSWORD}"
      HARPOCRATE_SYNC_LOG_RETENTION_DAYS: "30"
      HARPOCRATE_MQTT_MESSAGE_TTL_SECONDS: "1800"  # 30 minutes
    depends_on:
      mqtt:
        condition: service_healthy

  mqtt:
    image: emqx/emqx:5.6
    environment:
      EMQX_NODE_NAME: "emqx@mqtt"
      EMQX_MQTT__SESSION_EXPIRY_INTERVAL: "1800"   # persistent session 30min
      EMQX_MQTT__MESSAGE_EXPIRY_INTERVAL: "1800"   # TTL messages 30min
      EMQX_AUTHENTICATION__1__MECHANISM: "password_based"
      EMQX_AUTHENTICATION__1__BACKEND: "built_in_database"
    ports:
      - "1883:1883"    # MQTT
      - "18083:18083"  # Dashboard EMQX (admin)
    volumes:
      - mqtt_data:/opt/emqx/data
      - ./emqx/acl.conf:/opt/emqx/etc/acl.conf:ro
    healthcheck:
      test: ["CMD", "emqx", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  mqtt_data:
```

### ACL EMQX

```
# emqx/acl.conf
# Harpocrate : accès complet au topic de sync

{allow, {user, "harpocrate"}, publish,   ["harpocrate/sync/#"]}.
{allow, {user, "harpocrate"}, subscribe, ["harpocrate/sync/#"]}.
{deny,  all}.
```

---

## Partie 9 — UI sync state

### Page `/admin/replication/sync-state`

```
Cluster sync state
══════════════════════════════════════════════════════════════════

This node: instance-a
Push cursor: seq=247
MQTT: ✓ connected to mqtt:1883

─── Peers ───

┌─────────────┬──────────────┬──────────────┬──────────┬──────────┬────────┐
│ Peer        │ Last acked   │ Last applied │ Last seen│ Lag      │        │
├─────────────┼──────────────┼──────────────┼──────────┼──────────┼────────┤
│ instance-b  │ seq=245      │ seq=246      │ 2s ago   │ 2 msgs   │ [···]  │
│ instance-c  │ seq=247      │ seq=247      │ 1s ago   │ 0 msgs   │ [···]  │
└─────────────┴──────────────┴──────────────┴──────────┴──────────┴────────┘

─── Push cursor ───

Current push cursor: seq=247

⚠ Only reset the cursor manually if you know what you are doing.
  This will cause all instances to re-receive messages from the
  chosen sequence number.

Target sequence: [_____]  [↩ Reset push cursor]

─── Shelf ───

  instance-b: 0 messages pending
  instance-c: 0 messages pending

─── Sync log ───

  Oldest entry: 2026-04-04 (30 days ago)
  Newest entry: 2026-05-04 (today)
  Partitions: 30 active

  Retention: 30 days   [Edit]

  [Browse sync log →]
```

### Modal "Reset push cursor"

```
⚠ Reset push cursor

This will reset the push cursor to seq=<target>.
All messages from seq=<target>+1 to seq=247 will be
republished to the MQTT broker.

Affected peers:
  instance-b (currently at seq=245)
  instance-c (currently at seq=247 — no effect)

Estimated messages to republish: 2

Type "RESET CURSOR" to confirm:
┌────────────────────────────────┐
│                                │
└────────────────────────────────┘

[Cancel]  [Reset]
```

---

## Partie 10 — Endpoints admin

### `GET /v1/admin/replication/sync-state`

```json
{
  "instance_id": "instance-a",
  "push_cursor": 247,
  "mqtt_connected": true,
  "peers": [
    {
      "peer_emitter": "instance-b",
      "last_acked_seq": 245,
      "last_applied_seq": 246,
      "last_received_seq": 246,
      "last_seen_at": "...",
      "lag": 2,
      "status": "synced"
    }
  ],
  "shelf": {
    "instance-b": 0,
    "instance-c": 0
  },
  "sync_log": {
    "oldest_partition": "2026-04-04",
    "newest_partition": "2026-05-04",
    "partition_count": 30,
    "retention_days": 30
  }
}
```

### `POST /v1/admin/replication/reset-push-cursor`

```json
{ "target_seq": 245, "confirmation": "RESET CURSOR" }
```

---

## Critères de succès

1. ✅ Migration : `sync_log` partitionné, `sync_shelf`, `sync_replication_state`
2. ✅ Triggers sur toutes les tables métier → INSERT dans `sync_log`
3. ✅ `is_replication=true` via session variable Postgres
4. ✅ Ack inséré dans `sync_log` avec seq local continu
5. ✅ Self-filtering : messages propres ignorés
6. ✅ Publisher lit depuis cursor et publie dans l'ordre
7. ✅ Publisher persiste le cursor en DB
8. ✅ Consumer : messages dans l'ordre → appliqués directement
9. ✅ Consumer : messages hors-ordre → étagère persistante
10. ✅ Consumer : drain de l'étagère après application d'un message
11. ✅ `node_hello` publié au démarrage avec état de réplication
12. ✅ Réception hello → négociation automatique du cursor de push
13. ✅ Cursor reculé si peer a besoin de messages encore disponibles
14. ✅ Warning si messages purgés → peer doit restore
15. ✅ Résolution de conflits : `generation_version` gagne
16. ✅ Partitions créées automatiquement (7 jours à l'avance)
17. ✅ Purge automatique des partitions selon `SYNC_LOG_RETENTION_DAYS`
18. ✅ Docker Compose `cluster` avec EMQX
19. ✅ QoS 1 + persistent session, TTL messages 30min configurable
20. ✅ UI `/admin/replication/sync-state` : peers, lag, cursor, étagère
21. ✅ UI reset manuel du cursor avec double confirmation
22. ✅ Endpoint `GET /admin/replication/sync-state`
23. ✅ Endpoint `POST /admin/replication/reset-push-cursor`

## Pièges connus

- **Session variable Postgres `harpocrate.is_replication`** : doit être posée avec `SET LOCAL` (scope transaction) et non `SET` (scope session). Sinon toutes les transactions suivantes dans la même connexion poolée seraient marquées comme réplication.
- **BIGSERIAL et partitions** : la séquence BIGSERIAL est globale à la table mère, pas par partition. Les partitions héritent de la même séquence → ordering correct cross-partitions.
- **Drain de l'étagère en cascade** : si l'étagère contient 1000 messages consécutifs, le drain peut être long. Limiter à 100 messages par drain avec un yield asyncio entre batches pour ne pas bloquer l'event loop.
- **Persistent session MQTT + crash** : si le consumer crashe avec des messages QoS 1 non ackés, le broker les retransmet. Le consumer peut donc recevoir des doublons → la vérification `seq < next_expected` les élimine.
- **Cursor de push et partitions purgées** : si l'admin recule le cursor vers un seq appartenant à une partition purgée, le publisher ne trouvera rien à publier pour ces seqs. Il faut vérifier que le `oldest_available_seq` >= `target_cursor` avant d'accepter le reset.
- **Conflit sur wallet_grants** : les grants ont une PK composite `(wallet_id, grantee_user_id)`. L'upsert doit gérer correctement cette PK et ne pas utiliser uniquement `id`.
- **Taille des payloads MQTT** : un secret avec un `encrypted_value` RSA 2048 + padding fait ~300 bytes base64. Sur 10 000 secrets publiés en rafale → ~3 MB en queue. Acceptable pour EMQX (limite configurable, défaut 1MB par message → à augmenter à 10MB dans la config EMQX).
- **node_hello en boucle** : si deux instances démarrent simultanément, elles s'envoient mutuellement un hello et pourraient déclencher des resets de cursor en cascade. Introduire un délai aléatoire de 1-5s avant de traiter un hello reçu pour laisser le temps à la situation de se stabiliser.

## Ce qui suit

- **Lot 22** (déjà livré) — SDK Python détection rotation
- **Lot 23** — etcd 3 nœuds cross-host (pve1 + pve2)
- **Lot 24** — SDK npm `@harpocrate/sdk`
