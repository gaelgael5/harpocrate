# Lot 20 — Clustering Postgres : Patroni + etcd

> **Prérequis** : Lots 00-19.
> **Statut** : Implémentation — infrastructure + intégration Harpocrate.

## Objectif

Mettre en place un cluster Postgres **hautement disponible** avec Patroni et etcd, intégré dans Harpocrate via une **architecture extensible de stratégies de réplication**. L'admin choisit sa stratégie au déploiement via Docker Compose. L'UI Harpocrate s'adapte à la stratégie active.

Ce lot couvre :
1. L'infrastructure LXC (etcd + pg-primary + pg-replica)
2. La configuration Patroni
3. L'abstraction "stratégies de réplication" dans Harpocrate
4. L'intégration UI (monitoring, bascule, replicas)
5. La procédure de simulation failover + resynchronisation
6. La documentation GitHub

## Dépendances

- Lots 00-19
- Infrastructure Proxmox pve1 existante
- dnsmasq/Pi-hole sur `home.lan` existant
- Docker Swarm (CTID 300) existant

---

## Partie 1 — Infrastructure LXC

### LXC à créer sur pve1

```
CTID  Nom           RAM    CPU   Disk   IP                  Rôle
────  ────────────  ────   ───   ────   ──────────────────  ────────────────────
210   etcd          256MB  1     8GB    <ETCD_IP>           Store de consensus
211   pg-primary    2GB    2     32GB   <PG_PRIMARY_IP>     Postgres 16 + Patroni
212   pg-replica    2GB    2     32GB   <PG_REPLICA_IP>     Postgres 16 + Patroni
```

**Note** : les IPs sont des placeholders. L'admin remplace selon son plan d'adressage réseau. Exemple courant : `192.168.10.140`, `192.168.10.141`, `192.168.10.142`.

Tous les LXC sur le même bridge réseau que les autres services Harpocrate (bridge `vmbr0` ou équivalent).

### DNS dnsmasq

Ajouter dans la configuration dnsmasq/Pi-hole :

```bash
# /etc/dnsmasq.d/harpocrate.conf (ou équivalent Pi-hole)

# Primary Postgres — mis à jour par Patroni au failover
address=/postgres-primary.home.lan/<PG_PRIMARY_IP>

# Replica Postgres — statique
address=/postgres-replica.home.lan/<PG_REPLICA_IP>

# etcd — statique
address=/etcd.home.lan/<ETCD_IP>
```

`postgres-primary.home.lan` est l'entrée **dynamique** — le callback Patroni la met à jour lors d'un failover. Les autres sont statiques.

### Callback Patroni pour mise à jour DNS

Script appelé par Patroni à chaque changement de rôle :

```bash
#!/bin/bash
# /etc/patroni/callbacks/on_role_change.sh

EVENT=$1   # on_start, on_stop, on_role_change, on_reload
ROLE=$2    # master, replica, demoted
NAME=$3    # nom du nœud Patroni

if [ "$ROLE" = "master" ]; then
    # Récupérer l'IP de ce nœud
    MY_IP=$(hostname -I | awk '{print $1}')
    
    # Mettre à jour dnsmasq via API Pi-hole ou fichier direct
    SSH_CMD="ssh pihole.home.lan"
    
    $SSH_CMD "sed -i 's|address=/postgres-primary.home.lan/.*|address=/postgres-primary.home.lan/${MY_IP}|' /etc/dnsmasq.d/harpocrate.conf && pkill -SIGHUP dnsmasq"
    
    logger "Patroni: promoted to master, updated DNS postgres-primary.home.lan -> ${MY_IP}"
fi
```

**Prérequis** : clé SSH depuis les LXC Postgres vers le host Pi-hole. Ou, si Pi-hole est accessible en API :

```bash
# Via API Pi-hole v6
curl -X PATCH "http://pihole.home.lan/api/customdns" \
     -H "Authorization: Bearer $PIHOLE_API_KEY" \
     -d "{\"domain\": \"postgres-primary.home.lan\", \"ip\": \"${MY_IP}\"}"
```

---

## Partie 2 — etcd

### Installation (LXC 210)

```bash
# Ubuntu 24.04 LTS
apt-get update && apt-get install -y etcd-client etcd

# Ou via binaire direct (version pinée)
ETCD_VERSION="v3.5.12"
curl -L https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz \
     -o etcd.tar.gz
tar xzf etcd.tar.gz
mv etcd-${ETCD_VERSION}-linux-amd64/etcd* /usr/local/bin/
```

### Configuration etcd

```yaml
# /etc/etcd/etcd.conf.yml

name: etcd-node-1
data-dir: /var/lib/etcd

# Réseau
listen-peer-urls: http://<ETCD_IP>:2380
listen-client-urls: http://<ETCD_IP>:2379,http://127.0.0.1:2379
advertise-client-urls: http://<ETCD_IP>:2379
initial-advertise-peer-urls: http://<ETCD_IP>:2380

# Cluster initial (1 nœud pour l'instant, extensible à 3)
initial-cluster: etcd-node-1=http://<ETCD_IP>:2380
initial-cluster-token: harpocrate-etcd-cluster
initial-cluster-state: new

# Logs
log-level: info
log-outputs: [/var/log/etcd/etcd.log]

# Snapshots (retention)
snapshot-count: 10000
auto-compaction-retention: "1h"
```

**Préparé pour extension à 3 nœuds** : quand tu ajouteras un nœud sur pve2, il suffira de :
1. Ajouter le nouveau membre : `etcdctl member add etcd-node-2 --peer-urls http://<PVE2_IP>:2380`
2. Démarrer etcd sur pve2 avec `initial-cluster-state: existing`
3. Mettre à jour `initial-cluster` sur le nœud existant

### Service systemd etcd

```ini
# /etc/systemd/system/etcd.service

[Unit]
Description=etcd key-value store
Documentation=https://etcd.io/docs
After=network.target

[Service]
Type=notify
ExecStart=/usr/local/bin/etcd --config-file /etc/etcd/etcd.conf.yml
Restart=always
RestartSec=5s
LimitNOFILE=65536
User=etcd

[Install]
WantedBy=multi-user.target
```

### Vérification

```bash
# Vérifier que etcd répond
etcdctl --endpoints=http://<ETCD_IP>:2379 endpoint health

# Lister les membres
etcdctl --endpoints=http://<ETCD_IP>:2379 member list
```

---

## Partie 3 — Postgres + Patroni

### Installation (LXC 211 et 212, identique)

```bash
# Postgres 16
apt-get install -y postgresql-16 postgresql-client-16

# Patroni 3.x
pip install patroni[etcd3] psycopg2-binary

# Dépendances
apt-get install -y python3-pip python3-dev libpq-dev
```

### Variables d'environnement (.env)

```bash
# /etc/patroni/.env
# NE PAS COMMITER — exception documentée (voir lot 19, E-2)

PATRONI_SUPERUSER_PASSWORD=<strong_random_password>
PATRONI_REPLICATION_PASSWORD=<strong_random_password>
PATRONI_REWIND_PASSWORD=<strong_random_password>
```

### Configuration Patroni — Primary (LXC 211)

```yaml
# /etc/patroni/patroni.yml

scope: harpocrate-postgres
namespace: /patroni/
name: pg-primary

restapi:
  listen: <PG_PRIMARY_IP>:8008
  connect_address: <PG_PRIMARY_IP>:8008

etcd3:
  hosts: <ETCD_IP>:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576  # 1MB de lag max avant refus de failover

    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
        wal_level: replica
        hot_standby: "on"
        max_wal_senders: 5
        max_replication_slots: 5
        wal_log_hints: "on"
        archive_mode: "on"
        archive_command: "/bin/true"  # remplacer par commande WAL archiving si besoin
        synchronous_commit: "off"     # asynchrone (décision lot 20)

  initdb:
    - encoding: UTF8
    - data-checksums

  pg_hba:
    - host replication replicator <PG_REPLICA_IP>/32 md5
    - host replication replicator 127.0.0.1/32 trust
    - host all all 0.0.0.0/0 md5

  users:
    admin:
      password: "${PATRONI_SUPERUSER_PASSWORD}"
      options:
        - createrole
        - createdb
    replicator:
      password: "${PATRONI_REPLICATION_PASSWORD}"
      options:
        - replication

postgresql:
  listen: <PG_PRIMARY_IP>:5432
  connect_address: <PG_PRIMARY_IP>:5432
  data_dir: /var/lib/postgresql/16/main
  bin_dir: /usr/lib/postgresql/16/bin
  config_dir: /etc/postgresql/16/main

  authentication:
    replication:
      username: replicator
      password: "${PATRONI_REPLICATION_PASSWORD}"
    superuser:
      username: postgres
      password: "${PATRONI_SUPERUSER_PASSWORD}"
    rewind:
      username: rewind_user
      password: "${PATRONI_REWIND_PASSWORD}"

  parameters:
    max_connections: 100
    shared_buffers: 256MB
    effective_cache_size: 768MB
    work_mem: 4MB
    maintenance_work_mem: 64MB
    log_timezone: UTC
    timezone: UTC

tags:
  nofailover: false
  noloadbalance: false
  clonefrom: false
  nosync: false

callbacks:
  on_role_change: /etc/patroni/callbacks/on_role_change.sh
  on_start: /etc/patroni/callbacks/on_role_change.sh
```

### Configuration Patroni — Replica (LXC 212)

Identique au primary, avec deux différences :

```yaml
# /etc/patroni/patroni.yml (replica)

name: pg-replica   # ← différent

restapi:
  listen: <PG_REPLICA_IP>:8008
  connect_address: <PG_REPLICA_IP>:8008

postgresql:
  listen: <PG_REPLICA_IP>:5432
  connect_address: <PG_REPLICA_IP>:5432
```

### Service systemd Patroni

```ini
# /etc/systemd/system/patroni.service

[Unit]
Description=Patroni PostgreSQL HA
After=syslog.target network.target

[Service]
Type=simple
User=postgres
Group=postgres
EnvironmentFile=/etc/patroni/.env
ExecStart=/usr/local/bin/patroni /etc/patroni/patroni.yml
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=process
TimeoutSec=30
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

---

## Partie 4 — Stratégies de réplication dans Harpocrate

### Modèle de données

```sql
-- migrations/010_replication_strategies.sql

CREATE TABLE replication_strategies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type                TEXT NOT NULL,
    label               TEXT NOT NULL,
    description         TEXT,
    config              JSONB NOT NULL DEFAULT '{}',
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT replication_strategies_type_check
        CHECK (type IN ('none', 'patroni', 'harpocrate_sync', 's3_wal')),
    CONSTRAINT replication_strategies_one_active
        EXCLUDE (is_active WITH =) WHERE (is_active = TRUE)
);

CREATE TRIGGER trg_replication_strategies_updated_at
    BEFORE UPDATE ON replication_strategies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Seed : stratégie par défaut (none = standalone)
INSERT INTO replication_strategies (type, label, description, is_active)
VALUES ('none', 'Standalone', 'Single Postgres instance, no replication', TRUE);
```

La contrainte `EXCLUDE` garantit qu'une seule stratégie est active à la fois.

### Types de stratégies

```python
# app/core/replication.py

from enum import Enum

class ReplicationStrategyType(str, Enum):
    NONE = "none"               # Postgres standalone
    PATRONI = "patroni"         # Patroni + etcd (ce lot)
    HARPOCRATE_SYNC = "harpocrate_sync"  # Réplication applicative (lot futur C)
    S3_WAL = "s3_wal"          # WAL archiving continu vers S3 (lot futur)
```

### Config par stratégie (JSONB)

**`none`** :
```json
{}
```

**`patroni`** :
```json
{
  "patroni_api_urls": [
    "http://<PG_PRIMARY_IP>:8008",
    "http://<PG_REPLICA_IP>:8008"
  ],
  "replica_role": "read_non_critical",
  "primary_dsn": "postgresql://harpocrate:<pass>@postgres-primary.home.lan:5432/harpocrate",
  "replica_dsn": "postgresql://harpocrate:<pass>@postgres-replica.home.lan:5432/harpocrate"
}
```

**`harpocrate_sync`** (futur) :
```json
{
  "remote_instance_url": "https://vault2.yoops.org",
  "sync_interval_seconds": 60,
  "sync_direction": "bidirectional"
}
```

**`s3_wal`** (futur) :
```json
{
  "s3_endpoint": "https://...",
  "s3_bucket": "harpocrate-wal",
  "wal_archive_interval_seconds": 60
}
```

### Variable d'environnement

```bash
# .env
HARPOCRATE_REPLICATION_STRATEGY=none   # none | patroni | harpocrate_sync | s3_wal
```

Au démarrage, Harpocrate lit cette variable et active la stratégie correspondante en DB si elle n'existe pas encore.

### Service de réplication

```python
# app/services/replication.py

from abc import ABC, abstractmethod
from typing import Optional


class ReplicationStrategy(ABC):
    """Interface commune à toutes les stratégies de réplication."""

    @abstractmethod
    async def get_status(self) -> dict:
        """Retourne l'état de la réplication."""
        ...

    @abstractmethod
    async def get_replicas(self) -> list[dict]:
        """Retourne la liste des replicas."""
        ...

    @abstractmethod
    async def is_primary_healthy(self) -> bool:
        """Vérifie que le primary est sain."""
        ...

    async def get_replica_connection(self) -> Optional[asyncpg.Connection]:
        """Retourne une connexion vers un replica (si disponible)."""
        return None  # Default: pas de replica


class NoneStrategy(ReplicationStrategy):
    """Postgres standalone."""

    async def get_status(self) -> dict:
        return {"type": "none", "status": "ok", "replicas": []}

    async def get_replicas(self) -> list[dict]:
        return []

    async def is_primary_healthy(self) -> bool:
        return True  # Délégué au health check DB standard


class PatroniStrategy(ReplicationStrategy):
    """Patroni + etcd."""

    def __init__(self, config: dict):
        self.patroni_api_urls = config["patroni_api_urls"]
        self.replica_dsn = config.get("replica_dsn")
        self._replica_pool: Optional[asyncpg.Pool] = None

    async def get_status(self) -> dict:
        """Interroge l'API REST Patroni sur chaque nœud."""
        nodes = []
        for url in self.patroni_api_urls:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{url}/patroni", timeout=2) as resp:
                        data = await resp.json()
                        nodes.append({
                            "url": url,
                            "role": data.get("role"),
                            "state": data.get("state"),
                            "timeline": data.get("timeline"),
                            "lag": data.get("replication_state", {}).get("lag", 0),
                            "healthy": resp.status == 200,
                        })
            except Exception as e:
                nodes.append({"url": url, "healthy": False, "error": str(e)})

        primary = next((n for n in nodes if n.get("role") == "master"), None)
        replicas = [n for n in nodes if n.get("role") == "replica"]

        return {
            "type": "patroni",
            "status": "ok" if primary else "degraded",
            "primary": primary,
            "replicas": replicas,
        }

    async def get_replicas(self) -> list[dict]:
        status = await self.get_status()
        return status.get("replicas", [])

    async def is_primary_healthy(self) -> bool:
        status = await self.get_status()
        return status["status"] == "ok"

    async def get_replica_connection(self) -> Optional[asyncpg.Connection]:
        if not self.replica_dsn or not self._replica_pool:
            return None
        return await self._replica_pool.acquire()


def build_strategy(strategy_row: dict) -> ReplicationStrategy:
    """Factory : instancie la stratégie depuis la DB."""
    t = strategy_row["type"]
    config = strategy_row["config"]

    if t == "none":
        return NoneStrategy()
    elif t == "patroni":
        return PatroniStrategy(config)
    else:
        raise ValueError(f"Unknown replication strategy: {t}")
```

### Endpoints admin

#### `GET /v1/admin/replication/status`

```json
{
  "strategy": "patroni",
  "status": "ok",
  "primary": {
    "url": "http://<PG_PRIMARY_IP>:8008",
    "role": "master",
    "state": "running",
    "timeline": 3,
    "healthy": true
  },
  "replicas": [
    {
      "url": "http://<PG_REPLICA_IP>:8008",
      "role": "replica",
      "state": "streaming",
      "lag": 0,
      "healthy": true
    }
  ]
}
```

#### `GET /v1/admin/replication/strategies`

Liste des stratégies disponibles avec leur état.

#### `POST /v1/admin/replication/strategies/{id}/activate`

Bascule la stratégie active. Déclenche un redémarrage du pool de connexions Harpocrate.

---

## Partie 5 — Docker Compose

### `docker-compose.yml` — Standalone (pas de réplication)

```yaml
# docker-compose.yml
services:
  harpocrate:
    image: harpocrate:latest
    environment:
      HARPOCRATE_DB_DSN: postgresql://harpocrate:${DB_PASSWORD}@postgres:5432/harpocrate
      HARPOCRATE_REPLICATION_STRATEGY: none
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: harpocrate
      POSTGRES_USER: harpocrate
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U harpocrate"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### `docker-compose.patroni.yml` — Avec Patroni + etcd

```yaml
# docker-compose.patroni.yml
# Usage: docker compose -f docker-compose.yml -f docker-compose.patroni.yml up

services:
  harpocrate:
    environment:
      HARPOCRATE_DB_DSN: postgresql://harpocrate:${DB_PASSWORD}@postgres-primary.home.lan:5432/harpocrate
      HARPOCRATE_REPLICATION_STRATEGY: patroni
      HARPOCRATE_PATRONI_API_URLS: "http://<PG_PRIMARY_IP>:8008,http://<PG_REPLICA_IP>:8008"
      HARPOCRATE_POSTGRES_REPLICA_DSN: postgresql://harpocrate:${DB_PASSWORD}@postgres-replica.home.lan:5432/harpocrate
    # Pas de depends_on postgres ici : Postgres est externe (LXC)
```

**Note** : Postgres tourne dans des LXC dédiés (pas dans Docker), donc pas de service `postgres` dans ce compose. Harpocrate se connecte via DNS `home.lan`.

---

## Partie 6 — Intégration UI

### Page `/admin/replication`

```
Replication
══════════════════════════════════════════════════════

Strategy: Patroni + etcd                    [Change strategy]

─── Cluster status ───

  ✓ Primary    pg-primary (<PG_PRIMARY_IP>)
               State: running · Timeline: 3 · Connected since: 2h ago

  ✓ Replica    pg-replica (<PG_REPLICA_IP>)
               State: streaming · Lag: 0 bytes · In sync

─── Patroni nodes ───

  pg-primary   master    running   timeline=3   ✓ healthy
  pg-replica   replica   streaming lag=0        ✓ healthy

─── Actions ───

  [Trigger manual failover]   ⚠ Promotes pg-replica to primary
  [Reinitialize replica]      Resync pg-replica from current primary
  [Pause auto-failover]       Disable automatic promotion temporarily

Last refreshed: 30s ago  [Refresh now]
```

### Badge dans le header admin

Si la stratégie est `patroni` et qu'un replica est en retard (lag > seuil configuré) :

```
⚠ Replication lag: 45s
```

Click → `/admin/replication`.

### Page `/admin/replication/strategies`

```
Replication strategies
══════════════════════════════════════════════════════

★ Active: Patroni + etcd

Available strategies:

  ◉ None (standalone)
    Single Postgres instance. No replication.
    [Activate]

  ★ Patroni + etcd          ← active
    Streaming replication with automatic failover.
    Primary: postgres-primary.home.lan
    Replica: postgres-replica.home.lan
    [Configure]

  ○ Harpocrate Sync          (coming soon)
    Application-level replication between Harpocrate instances.

  ○ S3 WAL Archiving         (coming soon)
    Continuous WAL archiving to S3-compatible storage.
```

---

## Partie 7 — Procédure de simulation

### Pré-requis

```bash
# Vérifier l'état du cluster
patronictl -c /etc/patroni/patroni.yml list

# Résultat attendu :
# + Cluster: harpocrate-postgres --------+----+-----------+
# | Member     | Host            | Role   | TL | Lag in MB |
# +------------+-----------------+--------+----+-----------+
# | pg-primary | <PG_PRIMARY_IP> | Leader |  1 |           |
# | pg-replica | <PG_REPLICA_IP> | Replica|  1 |         0 |
# +------------+-----------------+--------+----+-----------+
```

### Simulation 1 — Failover automatique

```bash
# 1. Couper le primary (simuler une panne)
systemctl stop patroni   # sur LXC pg-primary

# 2. Observer la promotion (sur LXC pg-replica ou machine admin)
watch -n1 'patronictl -c /etc/patroni/patroni.yml list'

# Résultat attendu après ~15s (TTL Patroni) :
# pg-replica devient Leader, pg-primary absent

# 3. Vérifier que DNS a été mis à jour
dig postgres-primary.home.lan
# Doit répondre avec <PG_REPLICA_IP>

# 4. Vérifier qu'Harpocrate sert toujours
curl https://vault.yoops.org/health
# Doit retourner 200 ok

# 5. Vérifier dans l'UI Harpocrate
# → /admin/replication doit montrer pg-replica comme primary
```

### Simulation 2 — Retour de l'ancien primary

```bash
# 1. Redémarrer Patroni sur l'ancien primary
systemctl start patroni   # sur LXC pg-primary

# Patroni détecte qu'il y a déjà un leader (pg-replica)
# Il démarre automatiquement en mode replica
# pg_rewind resynchronise les données divergentes

# 2. Vérifier la resynchronisation
patronictl -c /etc/patroni/patroni.yml list

# Résultat attendu :
# pg-replica  Leader  (nouveau primary)
# pg-primary  Replica (ancien primary, maintenant replica, en sync)

# 3. Optionnel : switchover pour remettre pg-primary comme leader
patronictl -c /etc/patroni/patroni.yml switchover harpocrate-postgres \
    --master pg-replica \
    --candidate pg-primary \
    --scheduled now
```

### Simulation 3 — Failover manuel forcé (switchover)

```bash
# Bascule propre sans panne simulée
patronictl -c /etc/patroni/patroni.yml switchover harpocrate-postgres

# Patroni demande confirmation et effectue la bascule
# Zéro perte de données (flush du WAL avant bascule)
```

### Vérification de la resynchronisation

```bash
# Sur le replica (après retour)
psql -U postgres -c "SELECT * FROM pg_stat_replication;"
# Doit montrer une connexion active depuis le primary

# Vérifier le lag
psql -U postgres -c "
    SELECT client_addr, state, 
           pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
    FROM pg_stat_replication;
"
# lag_bytes doit converger vers 0
```

---

## Partie 8 — Lectures non-critiques sur replica

Quand `HARPOCRATE_REPLICATION_STRATEGY=patroni` et que la stratégie a un `replica_dsn`, Harpocrate peut envoyer certaines requêtes vers le replica.

### Requêtes autorisées sur replica

```python
# app/db/routing.py

REPLICA_SAFE_QUERIES = {
    # Lecture audit log (non-critique, léger lag OK)
    "audit_log.list",
    "audit_log.export",
    
    # Browse wallets (liste, pas lecture de secrets)
    "wallets.list",
    
    # Secret types (catalogue, rarement modifié)
    "secret_types.list",
    "secret_schemas.get",
    
    # Métriques et stats admin
    "admin.stats",
    "admin.replication.status",
}

REPLICA_FORBIDDEN_QUERIES = {
    # Tout ce qui touche epoch, sessions, auth
    "system_metadata.get_epoch",
    "api_keys.validate",
    "jwt.validate",
    
    # Lecture de secrets (cohérence stricte requise)
    "secrets.get",
    "secrets.list",
    
    # Grants (cohérence stricte)
    "grants.list",
    "grants.get",
    
    # Toutes les écritures
    "*write*",
}
```

### Connection pool dual

```python
# app/db/pool.py

class DualPool:
    """Pool primaire + pool replica optionnel."""

    def __init__(self, primary_dsn: str, replica_dsn: Optional[str] = None):
        self._primary_pool: asyncpg.Pool = None
        self._replica_pool: Optional[asyncpg.Pool] = None
        self._primary_dsn = primary_dsn
        self._replica_dsn = replica_dsn

    async def initialize(self):
        self._primary_pool = await asyncpg.create_pool(self._primary_dsn)
        if self._replica_dsn:
            try:
                self._replica_pool = await asyncpg.create_pool(self._replica_dsn)
            except Exception as e:
                logger.warning("replica_pool_init_failed", error=str(e))
                # Pas fatal : on continue sans replica

    def acquire(self, query_type: str = "default"):
        """Retourne le bon pool selon le type de requête."""
        if (
            self._replica_pool is not None
            and query_type in REPLICA_SAFE_QUERIES
        ):
            return self._replica_pool.acquire()
        return self._primary_pool.acquire()
```

---

## Partie 9 — Documentation GitHub

La documentation de déploiement est publiée sur GitHub dans `docs/ops/` :

```
docs/ops/
├── replication/
│   ├── README.md               (choisir sa stratégie)
│   ├── none.md                 (standalone, config minimale)
│   ├── patroni.md              (ce lot — installation étape par étape)
│   ├── harpocrate-sync.md      (placeholder — lot futur C)
│   └── s3-wal.md               (placeholder — lot futur)
├── patroni/
│   ├── installation.md         (LXC etcd + LXC pg-primary + LXC pg-replica)
│   ├── configuration.md        (fichiers patroni.yml annotés)
│   ├── failover-simulation.md  (procédures de test)
│   ├── dns-callback.md         (setup dnsmasq/Pi-hole)
│   └── troubleshooting.md      (erreurs courantes)
└── checklist-cluster.md        (checklist avant mise en prod)
```

### Checklist cluster (extrait)

```markdown
# Checklist avant mise en production cluster

## Infrastructure
- [ ] LXC etcd démarré et healthy (`etcdctl endpoint health`)
- [ ] LXC pg-primary démarré, Patroni actif, rôle Leader confirmé
- [ ] LXC pg-replica démarré, Patroni actif, rôle Replica confirmé, lag = 0
- [ ] DNS `postgres-primary.home.lan` résolu vers IP correcte
- [ ] DNS `postgres-replica.home.lan` résolu vers IP correcte

## Sécurité
- [ ] `/etc/patroni/.env` permissions 600, owner postgres
- [ ] Mots de passe Patroni forts (>32 chars random)
- [ ] pg_hba.conf : accès replication restreint aux IPs des LXC uniquement
- [ ] etcd sans auth TLS (OK pour réseau interne privé, à sécuriser si exposé)

## Harpocrate
- [ ] `HARPOCRATE_REPLICATION_STRATEGY=patroni` dans `.env`
- [ ] `HARPOCRATE_PATRONI_API_URLS` configuré avec les deux nœuds
- [ ] `/admin/replication` affiche primary + replica healthy
- [ ] Health check `GET /health` retourne `200 ok`

## Tests
- [ ] Simulation failover : coupure primary → replica promu en <30s
- [ ] Simulation retour : ancien primary resynchronisé automatiquement
- [ ] Switchover manuel testé
- [ ] DNS mis à jour automatiquement après failover
- [ ] Harpocrate continue à servir pendant le failover (pas de downtime >30s)
```

---

## Critères de succès

1. ✅ LXC etcd démarré, accessible, membre unique du cluster
2. ✅ LXC pg-primary : Patroni démarré, rôle Leader, Postgres 16 actif
3. ✅ LXC pg-replica : Patroni démarré, rôle Replica, streaming replication active, lag = 0
4. ✅ DNS `postgres-primary.home.lan` résolu correctement
5. ✅ Callback DNS fonctionnel : mise à jour dnsmasq après failover
6. ✅ Table `replication_strategies` migrée, stratégie `none` seedée
7. ✅ Service `PatroniStrategy` interroge l'API REST Patroni et retourne le statut
8. ✅ Endpoint `/admin/replication/status` répond avec primary + replicas
9. ✅ Page UI `/admin/replication` affiche le statut du cluster
10. ✅ Docker Compose standalone fonctionne (`docker-compose.yml`)
11. ✅ Docker Compose Patroni fonctionne (`docker-compose.patroni.yml`)
12. ✅ Simulation failover : coupure primary → replica promu en <30s
13. ✅ Simulation retour : resynchronisation automatique via pg_rewind
14. ✅ Simulation switchover manuel fonctionne
15. ✅ Harpocrate continue à servir pendant failover (reconnexion automatique via DNS)
16. ✅ Lectures non-critiques routées vers replica quand disponible
17. ✅ Documentation GitHub publiée (docs/ops/replication/ + docs/ops/patroni/)
18. ✅ Checklist cluster complète et validée

## Pièges connus

- **pg_rewind nécessite `wal_log_hints = on`** : déjà dans la config Patroni ci-dessus. Sans ça, la resynchronisation de l'ancien primary échoue et nécessite un `pg_basebackup` complet.
- **TTL Patroni (30s)** : délai avant détection de panne. Réduire à 15s possible mais augmente les faux positifs sur réseau lent.
- **DNS TTL** : dnsmasq a un TTL de cache. Harpocrate doit forcer la résolution DNS après failover (vider le cache asyncpg). Solution : pool de connexions avec `min_size=0` et reconnexion sur erreur.
- **etcd sans TLS** : acceptable sur réseau interne privé (`home.lan`). À sécuriser avec TLS mutuel si etcd est exposé sur un réseau non de confiance.
- **Fichier `.env` avec mots de passe Patroni** : permissions `600`, jamais dans git. Exception documentée (lot 19, E-2). Les secrets Patroni ne passent pas par Harpocrate (dépendance circulaire).
- **Callback DNS nécessite accès SSH** : les LXC Postgres doivent pouvoir atteindre le host Pi-hole en SSH. Clé SSH dédiée avec permissions minimales (uniquement `sed` sur le fichier dnsmasq).
- **Split-brain avec 1 nœud etcd** : si etcd tombe, Patroni ne peut plus faire de nouveau failover (mais le primary continue de servir). Acceptable pour ce lot. Résolu au passage à 3 nœuds etcd (pve2).
- **`maximum_lag_on_failover`** : si le replica a plus de 1MB de lag, Patroni refuse de le promouvoir (pour éviter une perte de données trop importante). Ajuster selon la tolérance au RPO.

## Ce qui suit

- **Lot 21** — Hypothèse C : réplication applicative Harpocrate → Harpocrate (multi-instance cross-datacenter, E2E preserved)
- **Lot 22** — Hypothèse D : SDK consommateurs avec détection de rotation de secrets et reconnexion automatique
- **Lot 23** — etcd 3 nœuds cross-host (pve1 + pve2) pour éliminer le SPOF etcd
