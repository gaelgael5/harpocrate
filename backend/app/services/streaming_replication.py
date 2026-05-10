"""Service streaming replication async (LOT réplication itération 1).

Approche : hors-app pour la mécanique basse niveau (`pg_basebackup`,
`postgresql.auto.conf`, `pg_hba.conf`). L'admin exécute les commandes en
SSH sur ses serveurs. Harpocrate :
  1. Crée le rôle Postgres `replicator_<...>` côté master (via le pool
     existant, qui doit avoir le droit CREATEROLE)
  2. Génère un bundle de 4 snippets prêts à copier-coller
  3. Surveille `pg_stat_replication` pour montrer l'état (streaming/lag/...)

Sécurité du password : généré aléatoirement (32 chars URL-safe), affiché
UNE fois dans la modale d'ajout, jamais re-affichable. Pas stocké en clair
côté Harpocrate (le master Postgres en a un hash, c'est suffisant).

Pas de SSH dans cette itération — l'admin garde la main.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from app.db.repositories import replication_nodes as nodes_repo


logger = structlog.get_logger(__name__)


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
    pg_hba = (
        f"host    replication    {replication_user}    {standby_host}/32    scram-sha-256"
    )

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
        last_seen_at=(
            row["last_seen_at"].isoformat() if row["last_seen_at"] else None
        ),
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


async def get_node(
    conn: asyncpg.Connection, node_id: UUID
) -> ReplicationNode | None:
    row = await nodes_repo.get_by_id(conn, node_id)
    return _row_to_dto(row) if row else None


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
) -> tuple[UUID, NodeBundle]:
    """Crée le rôle Postgres + insère le node + retourne le bundle.

    Tout est en transaction : si l'INSERT échoue, on DROP le rôle pour ne
    pas laisser d'orphelin côté master.
    """
    replication_user = make_replication_user(label)
    application_name = make_application_name(label)
    password = generate_password()

    async with conn.transaction():
        # 1) CREATE ROLE — pas de quote_ident ici, le user est généré par
        # `make_replication_user` qui n'utilise que [a-z0-9_] (pas d'injection
        # possible). Le password est passé en littéral après escape standard.
        # asyncpg ne paramétrise pas les CREATE ROLE — on écrit en SQL brut
        # avec un pg_quote_literal-like (doublement des single quotes).
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
        except Exception:
            # Best-effort cleanup : on tente de drop le rôle pour ne pas
            # laisser d'orphelin si l'INSERT a échoué (typiquement un label
            # déjà pris). La transaction sera rollback de toute façon, donc
            # le CREATE ROLE l'est aussi — mais on log au cas où.
            logger.warning(
                "replication_node_insert_failed_role_will_be_rolled_back",
                replication_user=replication_user,
            )
            raise

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


async def delete_node(
    conn: asyncpg.Connection, node_id: UUID
) -> bool:
    """Supprime un node : DROP ROLE côté master + DELETE row.

    Si le DROP ROLE échoue (le rôle est utilisé par une connexion active),
    on remonte l'erreur SANS supprimer la row — l'admin doit déconnecter
    le standby d'abord.
    """
    node = await get_node(conn, node_id)
    if node is None:
        return False

    async with conn.transaction():
        # On drop d'abord le rôle. Si ça échoue, la transaction rollback
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
    """Lit `pg_stat_replication` côté master et met à jour `last_state`/
    `last_lag_bytes`/`last_seen_at` pour chaque node DB qu'on retrouve par
    `application_name`.

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
    updated = 0

    # Mise à jour des nodes vus.
    for row in pg_stat_rows:
        node_row = await nodes_repo.get_by_application_name(
            conn, row["application_name"]
        )
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
            continue  # déjà marqué, pas la peine de re-écrire
        await conn.execute(
            "UPDATE replication_nodes SET last_state = 'disconnected' WHERE id = $1",
            n["id"],
        )
        updated += 1

    return updated


# ─── Reload pg_hba.conf ──────────────────────────────────────────────────────


async def reload_pg_hba(conn: asyncpg.Connection) -> None:
    """Demande à Postgres de relire `pg_hba.conf`. À appeler après que
    l'admin a modifié manuellement le fichier sur le master."""
    await conn.execute("SELECT pg_reload_conf()")
    logger.info("pg_hba_reloaded")
