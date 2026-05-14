"""Service streaming replication async (LOT réplication itérations 1-2).

Approche : hors-app pour la mécanique basse niveau (`pg_basebackup`,
`postgresql.auto.conf`, `pg_hba.conf`). L'admin exécute les commandes en
SSH sur ses serveurs. Harpocrate :
  1. Crée le rôle Postgres `replicator_<...>` côté master (via le pool
     existant, qui doit avoir le droit CREATEROLE)
  2. Génère un bundle de 4 snippets prêts à copier-coller
  3. Surveille `pg_stat_replication` pour montrer l'état (streaming/lag/...)
  4. **(it 2)** Historise les observations dans `replication_node_observations`
     et déclenche des `system_anomaly_events` quand le lag dépasse les seuils
     configurables.
  5. **(it 2)** Expose un test TCP de joignabilité du standby.

Sécurité du password : généré aléatoirement (32 chars URL-safe), affiché
UNE fois dans la modale d'ajout, jamais re-affichable. Pas stocké en clair
côté Harpocrate (le master Postgres en a un hash, c'est suffisant).

Pas de SSH dans cette itération — l'admin garde la main.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import asyncpg
import structlog

from app.db.repositories import replication_nodes as nodes_repo
from app.db.repositories import system_metadata as meta_repo
from app.services import system_anomalies as anomaly_svc

if TYPE_CHECKING:
    from app.services.pairing import ExistingNodeInfo


logger = structlog.get_logger(__name__)


# Clé system_metadata des seuils de lag. Modifiable via l'API.
LAG_THRESHOLDS_KEY = "replication_lag_thresholds"

DEFAULT_LAG_THRESHOLDS: dict[str, int] = {
    "warning_bytes": 64 * 1024 * 1024,  # 64 MB
    "critical_bytes": 512 * 1024 * 1024,  # 512 MB
}

# Rétention de l'historique d'observations.
OBSERVATIONS_RETENTION_DAYS = 7


# ─── Génération du nom de rôle / application_name ────────────────────────────


_LABEL_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify_label(label: str) -> str:
    """Convertit un label libre en slug ASCII utilisable dans un nom de rôle
    Postgres (a-z, 0-9, _). Préserve la lisibilité.
    """
    s = label.strip().lower()
    s = _LABEL_SLUG_RE.sub("_", s)
    s = s.strip("_")
    return s or "node"


def make_replication_user(label: str) -> str:
    """Construit un nom de rôle unique : `repl_<slug>_<6-char-rand>`.
    Le suffixe random évite les collisions si deux labels différents donnent
    le même slug (ex: `LXC voisin` et `lxc-voisin`)."""
    slug = _slugify_label(label)[:32]
    return f"repl_{slug}_{secrets.token_hex(3)}"


def make_application_name(label: str) -> str:
    """`application_name` apparait dans `pg_stat_replication`. On utilise le
    slug du label pour qu'il soit lisible côté monitoring."""
    return _slugify_label(label)[:48] or f"node_{secrets.token_hex(3)}"


def generate_password() -> str:
    """Password URL-safe 32 chars (~192 bits d'entropie). Utilisable dans
    `primary_conninfo` sans escape."""
    return secrets.token_urlsafe(32)


# ─── Bundle de snippets pour l'admin ──────────────────────────────────────────


@dataclass(frozen=True)
class NodeBundle:
    """Bundle de configuration retourné UNE fois après création d'un node.

    Le password est INCLUS ici (seule occasion de le voir côté admin). Le
    backend ne le persiste pas — seul le hash dans `pg_authid` côté master
    est conservé.
    """

    node_id: UUID
    replication_user: str
    application_name: str
    password: str  # affiché 1x, jamais re-affichable
    master_pg_hba_line: str
    standby_pg_basebackup_command: str
    standby_postgresql_auto_conf: str
    standby_signal_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "replication_user": self.replication_user,
            "application_name": self.application_name,
            "password": self.password,
            "master_pg_hba_line": self.master_pg_hba_line,
            "standby_pg_basebackup_command": self.standby_pg_basebackup_command,
            "standby_postgresql_auto_conf": self.standby_postgresql_auto_conf,
            "standby_signal_command": self.standby_signal_command,
        }


def _build_bundle(
    *,
    node_id: UUID,
    replication_user: str,
    application_name: str,
    password: str,
    master_host: str,
    master_port: int,
    standby_host: str,
    standby_data_dir: str = "/var/lib/postgresql/16/main",
) -> NodeBundle:
    """Construit le bundle de 4 snippets à exécuter par l'admin.

    NOTE : `master_host` est l'adresse IP/hostname du master tel que vu
    DEPUIS le standby. C'est l'admin qui sait (peut être l'IP LAN, peut
    être un hostname public). On ne cherche pas à deviner.

    Le `standby_data_dir` est par défaut le path Debian/Ubuntu (PG 16). Si
    l'admin utilise un layout différent (Docker, RPM...), il adapte.
    """
    pg_hba = f"host    replication    {replication_user}    {standby_host}/32    scram-sha-256"

    pg_basebackup = (
        f"# À exécuter côté STANDBY, en tant que postgres :\n"
        f"sudo systemctl stop postgresql\n"
        f"sudo -u postgres rm -rf {standby_data_dir}/*\n"
        f"sudo -u postgres PGPASSWORD='{password}' pg_basebackup \\\n"
        f"    -h {master_host} -p {master_port} \\\n"
        f"    -U {replication_user} \\\n"
        f"    -D {standby_data_dir} \\\n"
        f"    -Fp -Xs -P -R"
    )

    pg_auto_conf = (
        f"# À AJOUTER à {standby_data_dir}/postgresql.auto.conf si pas\n"
        f"# déjà présent (l'option -R de pg_basebackup l'écrit normalement) :\n"
        f"primary_conninfo = 'host={master_host} port={master_port} "
        f"user={replication_user} password={password} application_name={application_name}'\n"
        f"primary_slot_name = ''  # à remplir si tu utilises un slot de réplication"
    )

    standby_signal = (
        f"# À exécuter côté STANDBY :\n"
        f"sudo -u postgres touch {standby_data_dir}/standby.signal\n"
        f"sudo systemctl start postgresql"
    )

    return NodeBundle(
        node_id=node_id,
        replication_user=replication_user,
        application_name=application_name,
        password=password,
        master_pg_hba_line=pg_hba,
        standby_pg_basebackup_command=pg_basebackup,
        standby_postgresql_auto_conf=pg_auto_conf,
        standby_signal_command=standby_signal,
    )


# ─── DTO node ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplicationNode:
    id: UUID
    strategy_id: UUID
    label: str
    host: str
    port: int
    replication_user: str
    application_name: str
    role: str
    notes: str | None
    last_seen_at: str | None
    last_state: str | None
    last_lag_bytes: int | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "strategy_id": str(self.strategy_id),
            "label": self.label,
            "host": self.host,
            "port": self.port,
            "replication_user": self.replication_user,
            "application_name": self.application_name,
            "role": self.role,
            "notes": self.notes,
            "last_seen_at": self.last_seen_at,
            "last_state": self.last_state,
            "last_lag_bytes": self.last_lag_bytes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_dto(row: asyncpg.Record) -> ReplicationNode:
    return ReplicationNode(
        id=row["id"],
        strategy_id=row["strategy_id"],
        label=row["label"],
        host=row["host"],
        port=row["port"],
        replication_user=row["replication_user"],
        application_name=row["application_name"],
        role=row["role"],
        notes=row["notes"],
        last_seen_at=(row["last_seen_at"].isoformat() if row["last_seen_at"] else None),
        last_state=row["last_state"],
        last_lag_bytes=row["last_lag_bytes"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


# ─── Opérations ───────────────────────────────────────────────────────────────


async def list_nodes(
    conn: asyncpg.Connection,
    strategy_id: UUID | None = None,
) -> list[ReplicationNode]:
    if strategy_id is not None:
        rows = await nodes_repo.list_for_strategy(conn, strategy_id)
    else:
        rows = await nodes_repo.list_all(conn)
    return [_row_to_dto(r) for r in rows]


async def get_node(conn: asyncpg.Connection, node_id: UUID) -> ReplicationNode | None:
    row = await nodes_repo.get_by_id(conn, node_id)
    return _row_to_dto(row) if row else None


async def _create_role_and_insert_node(
    conn: asyncpg.Connection,
    *,
    strategy_id: UUID,
    label: str,
    host: str,
    port: int,
    role: str,
    notes: str | None,
    replication_user: str,
    application_name: str,
    password: str,
    created_by_user_id: UUID | None,
) -> UUID:
    """CREATE ROLE + INSERT row dans une seule transaction.

    Le password est échappé pour le littéral SQL (doublement des single quotes).
    Sur erreur, la transaction est rollback atomiquement (CREATE ROLE + INSERT
    forment une unité). Les `UniqueViolationError` propagent silencieusement
    pour que le caller les traduise en exception métier ; toute autre erreur
    est loggée avec son contexte avant propagation.
    """
    async with conn.transaction():
        safe_password = password.replace("'", "''")
        await conn.execute(
            f"CREATE ROLE {replication_user} REPLICATION LOGIN PASSWORD '{safe_password}'"
        )
        try:
            node_id = await nodes_repo.insert(
                conn,
                strategy_id=strategy_id,
                label=label,
                host=host,
                port=port,
                replication_user=replication_user,
                application_name=application_name,
                role=role,
                notes=notes,
                created_by_user_id=created_by_user_id,
            )
        except asyncpg.UniqueViolationError:
            raise
        except Exception:
            logger.warning(
                "replication_node_insert_failed",
                replication_user=replication_user,
                label=label,
                application_name=application_name,
                strategy_id=str(strategy_id),
            )
            raise
        # Crée le replication slot physique côté master. pg_basebackup --slot=
        # côté standby suppose que le slot existe déjà. Le nom du slot = celui
        # de l'application_name pour pouvoir corréler facilement les rows de
        # pg_stat_replication / pg_replication_slots à un node Harpocrate.
        slot_exists = await conn.fetchval(
            "SELECT 1 FROM pg_replication_slots WHERE slot_name = $1",
            application_name,
        )
        if not slot_exists:
            await conn.execute(
                "SELECT pg_create_physical_replication_slot($1)",
                application_name,
            )
        return node_id


async def add_node(
    conn: asyncpg.Connection,
    *,
    strategy_id: UUID,
    label: str,
    host: str,
    port: int,
    role: str,
    notes: str | None,
    master_host: str,
    master_port: int,
    standby_data_dir: str = "/var/lib/postgresql/16/main",
    created_by_user_id: UUID | None = None,
    replace_existing: bool = False,
) -> tuple[UUID, NodeBundle]:
    """Crée le rôle Postgres + insère le node + retourne le bundle.

    Tout est en transaction : si l'INSERT échoue, on DROP le rôle pour ne
    pas laisser d'orphelin côté master. Si l'INSERT échoue à cause d'un
    conflit d'unicité sur `label` ou `application_name` :
      - `replace_existing=False` (défaut) : lève `NodeAlreadyExistsError`
        avec les détails du node existant.
      - `replace_existing=True` : supprime l'ancien node (DROP ROLE +
        DELETE row) puis réessaie l'insert dans une nouvelle transaction.
    """
    from app.services.pairing import NodeAlreadyExistsError

    replication_user = make_replication_user(label)
    application_name = make_application_name(label)
    password = generate_password()

    try:
        node_id = await _create_role_and_insert_node(
            conn,
            strategy_id=strategy_id,
            label=label,
            host=host,
            port=port,
            role=role,
            notes=notes,
            replication_user=replication_user,
            application_name=application_name,
            password=password,
            created_by_user_id=created_by_user_id,
        )
    except asyncpg.UniqueViolationError as exc:
        existing = await _load_existing_node_details(
            conn,
            label=label,
            application_name=application_name,
        )
        if existing is None:
            logger.warning(
                "replication_node_unique_violation_on_unknown_constraint",
                label=label,
                application_name=application_name,
                replication_user=replication_user,
                constraint_name=getattr(exc, "constraint_name", None),
            )
            raise
        if not replace_existing:
            raise NodeAlreadyExistsError(existing) from exc

        # Remplacement explicite : delete (DROP ROLE + DELETE row) + retry.
        # La transaction précédente a déjà rollbacké (UniqueViolation la
        # rollbacke automatiquement) — on ouvre une nouvelle transaction.
        existing_id = UUID(existing["id"])
        await delete_node(conn, existing_id)
        node_id = await _create_role_and_insert_node(
            conn,
            strategy_id=strategy_id,
            label=label,
            host=host,
            port=port,
            role=role,
            notes=notes,
            replication_user=replication_user,
            application_name=application_name,
            password=password,
            created_by_user_id=created_by_user_id,
        )
        logger.info(
            "replication_node_replaced",
            old_node_id=str(existing_id),
            new_label=label,
            new_node_id=str(node_id),
            new_replication_user=replication_user,
        )

    bundle = _build_bundle(
        node_id=node_id,
        replication_user=replication_user,
        application_name=application_name,
        password=password,
        master_host=master_host,
        master_port=master_port,
        standby_host=host,
        standby_data_dir=standby_data_dir,
    )
    logger.info(
        "replication_node_added",
        node_id=str(node_id),
        replication_user=replication_user,
        application_name=application_name,
        standby_host=host,
    )
    return node_id, bundle


async def _load_existing_node_details(
    conn: asyncpg.Connection,
    *,
    label: str,
    application_name: str,
) -> ExistingNodeInfo | None:
    """Récupère le node existant qui a déclenché la `UniqueViolationError`.

    Le conflit peut venir de l'index sur `LOWER(label)` ou sur
    `LOWER(application_name)` — on cherche les deux.
    """
    row = await conn.fetchrow(
        """
        SELECT id, label, host, application_name, last_state, last_seen_at
        FROM replication_nodes
        WHERE LOWER(label) = LOWER($1) OR LOWER(application_name) = LOWER($2)
        LIMIT 1
        """,
        label,
        application_name,
    )
    if row is None:
        return None
    last_seen_at = row["last_seen_at"]
    return {
        "id": str(row["id"]),
        "label": row["label"],
        "host": row["host"],
        "application_name": row["application_name"],
        "last_state": row["last_state"],
        "last_seen_at": last_seen_at.isoformat() if last_seen_at is not None else None,
    }


async def delete_node(conn: asyncpg.Connection, node_id: UUID) -> bool:
    """Supprime un node : DROP ROLE côté master + DELETE row.

    Si le DROP ROLE échoue (le rôle est utilisé par une connexion active),
    on remonte l'erreur SANS supprimer la row — l'admin doit déconnecter
    le standby d'abord.
    """
    node = await get_node(conn, node_id)
    if node is None:
        return False

    async with conn.transaction():
        # Drop le slot de réplication s'il existe encore. Sans ça, un slot
        # orphelin reste actif côté master et bloque la création d'un nouveau
        # slot du même nom lors d'un replace.
        slot_exists = await conn.fetchval(
            "SELECT 1 FROM pg_replication_slots WHERE slot_name = $1",
            node.application_name,
        )
        if slot_exists:
            try:
                await conn.execute(
                    "SELECT pg_drop_replication_slot($1)",
                    node.application_name,
                )
            except asyncpg.PostgresError as exc:
                logger.warning(
                    "replication_slot_drop_failed",
                    node_id=str(node_id),
                    slot_name=node.application_name,
                    error=str(exc),
                )
                raise

        # On drop ensuite le rôle. Si ça échoue, la transaction rollback
        # et la row reste en DB — l'admin peut retry après avoir débranché
        # le standby.
        try:
            await conn.execute(f"DROP ROLE IF EXISTS {node.replication_user}")
        except asyncpg.PostgresError as exc:
            logger.warning(
                "replication_node_drop_role_failed",
                node_id=str(node_id),
                replication_user=node.replication_user,
                error=str(exc),
            )
            raise

        await nodes_repo.delete(conn, node_id)

    logger.info("replication_node_deleted", node_id=str(node_id))
    return True


# ─── Surveillance ─────────────────────────────────────────────────────────────


async def refresh_nodes_state(conn: asyncpg.Connection) -> int:
    """Lit `pg_stat_replication` côté master, met à jour `last_state`/
    `last_lag_bytes`/`last_seen_at`, historise dans observations et déclenche
    une anomalie si le lag dépasse les seuils configurables.

    Pour les nodes DB qui n'apparaissent PAS dans pg_stat_replication, on
    marque `last_state='disconnected'` SI on les avait déjà vus avant
    (`last_seen_at` non NULL) — sinon ils restent en `unknown` (jamais
    connectés).

    Retourne le nombre de nodes mis à jour.
    """
    pg_stat_rows = await conn.fetch(
        """
        SELECT application_name, state,
               pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
        FROM pg_stat_replication
        WHERE application_name IS NOT NULL
        """
    )
    seen_app_names = {r["application_name"] for r in pg_stat_rows}

    now = datetime.now(timezone.utc)
    thresholds = await get_lag_thresholds(conn)
    updated = 0

    # Mise à jour des nodes vus.
    for row in pg_stat_rows:
        node_row = await nodes_repo.get_by_application_name(conn, row["application_name"])
        if node_row is None:
            continue  # standby physique inconnu de Harpocrate, on ignore
        state = row["state"] if row["state"] in ("streaming", "catchup") else "unknown"
        lag = int(row["lag_bytes"]) if row["lag_bytes"] is not None else None
        await nodes_repo.update_observed_state(
            conn,
            node_id=node_row["id"],
            last_seen_at=now,
            last_state=state,
            last_lag_bytes=lag,
        )
        # (it2) historise + check seuil de lag
        await record_observation(
            conn,
            node_id=node_row["id"],
            state=state,
            lag_bytes=lag,
            observed_at=now,
        )
        await check_lag_threshold(
            conn,
            node_id=node_row["id"],
            node_label=node_row["label"],
            lag_bytes=lag,
            thresholds=thresholds,
        )
        updated += 1

    # Pour les nodes DB qui ne figurent plus dans pg_stat_replication mais
    # qu'on avait déjà vus → marqués 'disconnected'. On ne touche pas
    # last_seen_at (le timestamp où le standby était last alive est utile
    # pour diagnostiquer "down depuis combien de temps").
    all_nodes = await nodes_repo.list_all(conn)
    for n in all_nodes:
        if n["application_name"] in seen_app_names:
            continue
        if n["last_seen_at"] is None:
            continue  # jamais connecté → on garde 'unknown'
        if n["last_state"] == "disconnected":
            # On historise quand même pour ne pas avoir de "trou" dans le
            # graph de la page détaillée (lag_bytes=NULL côté disconnected).
            await record_observation(
                conn,
                node_id=n["id"],
                state="disconnected",
                lag_bytes=None,
                observed_at=now,
            )
            continue
        await conn.execute(
            "UPDATE replication_nodes SET last_state = 'disconnected' WHERE id = $1",
            n["id"],
        )
        await record_observation(
            conn,
            node_id=n["id"],
            state="disconnected",
            lag_bytes=None,
            observed_at=now,
        )
        updated += 1

    return updated


# ─── Reload pg_hba.conf ──────────────────────────────────────────────────────


async def reload_pg_hba(conn: asyncpg.Connection) -> None:
    """Demande à Postgres de relire `pg_hba.conf`. À appeler après que
    l'admin a modifié manuellement le fichier sur le master."""
    await conn.execute("SELECT pg_reload_conf()")
    logger.info("pg_hba_reloaded")


# ─── (it2) TCP ping ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TcpPingResult:
    ok: bool
    latency_ms: float | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "latency_ms": self.latency_ms, "error": self.error}


async def tcp_ping(host: str, port: int, *, timeout: float = 2.0) -> TcpPingResult:
    """Teste juste la joignabilité TCP du `host:port` depuis Harpocrate.

    Pas d'auth Postgres : le password de réplication n'est pas stocké côté
    Harpocrate (zero-knowledge). Ce check répond à la question "le réseau
    me laisse-t-il atteindre le standby ?" — pas plus. La vraie validation
    fonctionnelle (le standby reçoit-il les WAL ?) est faite par
    `refresh_nodes_state` via `pg_stat_replication`.
    """
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        # asyncio.open_connection(host, port) ouvre un socket TCP.
        # On ferme immédiatement après — pas de handshake protocolaire.
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=port), timeout=timeout
        )
    except asyncio.TimeoutError:
        return TcpPingResult(ok=False, latency_ms=None, error=f"timeout after {timeout}s")
    except OSError as exc:
        return TcpPingResult(ok=False, latency_ms=None, error=str(exc))
    latency = (loop.time() - t0) * 1000.0

    # Cleanup propre du socket.
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass
    return TcpPingResult(ok=True, latency_ms=round(latency, 2), error=None)


async def test_node_connect(conn: asyncpg.Connection, node_id: UUID) -> TcpPingResult | None:
    """Récupère le node + lance tcp_ping. None si node introuvable."""
    node = await get_node(conn, node_id)
    if node is None:
        return None
    return await tcp_ping(node.host, node.port)


# ─── (it2) Observations + purge ─────────────────────────────────────────────


async def record_observation(
    conn: asyncpg.Connection,
    *,
    node_id: UUID,
    state: str,
    lag_bytes: int | None,
    observed_at: datetime | None = None,
) -> int:
    """Insère une row dans `replication_node_observations`. Pas de dédoublonnage :
    chaque tick crée une row (la purge gère le volume)."""
    return await conn.fetchval(
        """
        INSERT INTO replication_node_observations (node_id, observed_at, state, lag_bytes)
        VALUES ($1, COALESCE($2, NOW()), $3, $4)
        RETURNING id
        """,
        node_id,
        observed_at,
        state,
        lag_bytes,
    )


async def list_observations(
    conn: asyncpg.Connection,
    *,
    node_id: UUID,
    since: datetime,
    limit: int = 5000,
) -> list[asyncpg.Record]:
    """Liste les observations d'un node depuis `since`, ordre chronologique."""
    return await conn.fetch(
        """
        SELECT observed_at, state, lag_bytes
        FROM replication_node_observations
        WHERE node_id = $1 AND observed_at >= $2
        ORDER BY observed_at ASC
        LIMIT $3
        """,
        node_id,
        since,
        limit,
    )


async def purge_old_observations(
    conn: asyncpg.Connection,
    *,
    days: int = OBSERVATIONS_RETENTION_DAYS,
) -> int:
    """Supprime les observations plus anciennes que `days` jours. Retourne
    le nombre de rows supprimées."""
    result = await conn.execute(
        """
        DELETE FROM replication_node_observations
        WHERE observed_at < NOW() - $1::interval
        """,
        f"{days} days",
    )
    try:
        deleted = int(result.split(" ")[1])
    except (IndexError, ValueError):
        deleted = 0
    if deleted > 0:
        logger.info(
            "replication_observations_purged",
            deleted=deleted,
            retention_days=days,
        )
    return deleted


# ─── (it2) Seuils de lag ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class LagThresholds:
    warning_bytes: int
    critical_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "warning_bytes": self.warning_bytes,
            "critical_bytes": self.critical_bytes,
        }


async def get_lag_thresholds(conn: asyncpg.Connection) -> LagThresholds:
    raw = await meta_repo.get_value(conn, LAG_THRESHOLDS_KEY)
    if raw is None:
        return LagThresholds(**DEFAULT_LAG_THRESHOLDS)
    if isinstance(raw, str):
        raw = json.loads(raw)
    return LagThresholds(
        warning_bytes=int(raw.get("warning_bytes", DEFAULT_LAG_THRESHOLDS["warning_bytes"])),
        critical_bytes=int(raw.get("critical_bytes", DEFAULT_LAG_THRESHOLDS["critical_bytes"])),
    )


async def set_lag_thresholds(
    conn: asyncpg.Connection,
    *,
    warning_bytes: int,
    critical_bytes: int,
) -> LagThresholds:
    if warning_bytes < 0 or critical_bytes < 0:
        raise ValueError("lag thresholds must be non-negative")
    if warning_bytes > critical_bytes:
        # On tolère l'inversion mais on remonte une erreur claire — sinon
        # check_lag_threshold ne déclencherait jamais le seuil critical.
        raise ValueError("warning_bytes must be <= critical_bytes")
    new = LagThresholds(warning_bytes=warning_bytes, critical_bytes=critical_bytes)
    await meta_repo.set_value(conn, LAG_THRESHOLDS_KEY, new.to_dict())
    logger.info(
        "replication_lag_thresholds_updated",
        warning_bytes=warning_bytes,
        critical_bytes=critical_bytes,
    )
    return new


# ─── (it2) Détection de drift ────────────────────────────────────────────────


_ANOMALY_TYPE_BY_SEVERITY: dict[str, str] = {
    "warning": "replication_lag_warning",
    "critical": "replication_lag_critical",
}


async def _has_open_lag_anomaly(
    conn: asyncpg.Connection,
    *,
    node_id: UUID,
    severity: Literal["warning", "critical"],
) -> bool:
    """Hystérésis : retourne True si une anomalie de cette severity existe
    déjà pour ce node ET n'est pas acquittée. Évite le spam d'anomalies à
    chaque tick tant que le lag reste haut."""
    anomaly_type = _ANOMALY_TYPE_BY_SEVERITY[severity]
    row = await conn.fetchval(
        """
        SELECT 1 FROM system_anomaly_events
        WHERE source = 'replication_lag'
          AND source_ref_id = $1
          AND anomaly_type = $2
          AND acknowledged_at IS NULL
        LIMIT 1
        """,
        node_id,
        anomaly_type,
    )
    return row is not None


async def check_lag_threshold(
    conn: asyncpg.Connection,
    *,
    node_id: UUID,
    node_label: str,
    lag_bytes: int | None,
    thresholds: LagThresholds,
) -> str | None:
    """Crée une anomalie système si le lag dépasse un seuil ET qu'aucune
    anomalie ouverte n'existe déjà pour ce (node, severity).

    Retourne la severity déclenchée ('warning'|'critical') ou None.
    Le seuil critical prime sur le seuil warning : on ne crée pas les deux
    pour un même tick.
    """
    if lag_bytes is None:
        return None

    severity: Literal["warning", "critical"] | None = None
    if lag_bytes >= thresholds.critical_bytes:
        severity = "critical"
    elif lag_bytes >= thresholds.warning_bytes:
        severity = "warning"
    if severity is None:
        return None

    if await _has_open_lag_anomaly(conn, node_id=node_id, severity=severity):
        return severity  # déjà signalé, pas la peine de re-créer

    await anomaly_svc.report(
        conn,
        severity=severity,
        anomaly_type=_ANOMALY_TYPE_BY_SEVERITY[severity],
        source="replication_lag",
        source_ref_id=node_id,
        message=(
            f"Standby {node_label!r} replication lag is "
            f"{lag_bytes / (1024 * 1024):.1f} MB "
            f"(threshold {severity}: "
            f"{(thresholds.critical_bytes if severity == 'critical' else thresholds.warning_bytes) / (1024 * 1024):.1f} MB)"
        ),
        metadata={
            "node_id": str(node_id),
            "node_label": node_label,
            "lag_bytes": lag_bytes,
            "warning_bytes": thresholds.warning_bytes,
            "critical_bytes": thresholds.critical_bytes,
        },
    )
    return severity


# ─── (it2.5) Postgres info — pour copier la config master vers standby ──────


# Liste des paramètres `pg_settings` utiles pour configurer une réplication.
# Choisi pour matcher exactement ce dont l'admin a besoin pour configurer un
# standby :
#   - `version`              : matcher la version PG entre master et standby
#                              (sinon pg_basebackup refuse)
#   - `data_directory`       : utile au pg_basebackup côté standby (souvent
#                              identique des deux côtés)
#   - `config_file`/`hba_file`: paths absolus côté master, à connaître pour
#                              modifier pg_hba.conf
#   - `wal_level`            : doit valoir 'replica' (ou 'logical') sinon le
#                              standby ne peut pas streamer
#   - `max_wal_senders`      : doit être >= nombre de standbys + 1 marge
#   - `max_replication_slots`: idem si on utilise des slots
#   - `port` / `listen_addresses` : pour construire `primary_conninfo`
#
# Tous lus en une seule query via `pg_settings WHERE name = ANY(...)`.
_PG_SETTINGS_TO_EXPOSE: tuple[str, ...] = (
    "data_directory",
    "config_file",
    "hba_file",
    "wal_level",
    "max_wal_senders",
    "max_replication_slots",
    "wal_keep_size",
    "archive_mode",
    "port",
    "listen_addresses",
    "server_version",
)


@dataclass(frozen=True)
class PostgresInfo:
    """Snapshot des params Postgres de l'instance courante."""

    settings: dict[str, str]  # name → value (string)
    version: str  # full version string (SELECT version())
    server_addr: str | None  # IP côté serveur, NULL si socket UNIX local

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "version": self.version,
            "server_addr": self.server_addr,
        }


async def get_postgres_info(conn: asyncpg.Connection) -> PostgresInfo:
    """Lit les paramètres Postgres utiles à la configuration d'un standby.

    Tout est lu en lecture seule. Aucun side-effect.
    """
    settings_rows = await conn.fetch(
        "SELECT name, setting FROM pg_settings WHERE name = ANY($1::text[])",
        list(_PG_SETTINGS_TO_EXPOSE),
    )
    settings = {row["name"]: row["setting"] for row in settings_rows}

    # version() retourne la chaîne complète "PostgreSQL 16.1 on x86_64-...".
    version = await conn.fetchval("SELECT version()")

    # inet_server_addr() = IP du serveur PG vue depuis cette connexion ;
    # NULL si on est connecté via socket UNIX local. Utile pour confirmer
    # à l'admin où PG écoute réellement.
    server_addr_raw = await conn.fetchval("SELECT inet_server_addr()::text")
    server_addr = server_addr_raw if server_addr_raw else None

    return PostgresInfo(
        settings=settings,
        version=str(version) if version else "",
        server_addr=server_addr,
    )


# ─── (LOT 3 stub) Hook is_standby_of ─────────────────────────────────────────


async def set_standby_of(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    master_url: str | None,
) -> None:
    """Marque ou démarque cette instance comme asservie à un master (LOT 3 stub).

    Implémentation complète dans LOT 5. À ce stade : juste set la clé
    `replication.is_standby_of` dans `system_metadata` (NULL = pas asservi).
    """
    await meta_repo.set_value(conn, "replication.is_standby_of", master_url)
