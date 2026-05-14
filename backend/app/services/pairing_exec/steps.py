"""Déclaration des 7 étapes du wizard pairing standby.

Chaque `StepDescriptor` porte le titre FR, une description longue (le « pourquoi »)
et un identifiant `kind` qui pilote le dispatch côté Executor (DockerExecutor ou
NativeSshExecutor traduisent ce kind en commande concrète).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StepKind = Literal[
    "stop_pg_container",
    "backup_pg_data_dir",
    "pg_basebackup_from_master",
    "verify_standby_signal",
    "verify_auto_conf",
    "start_pg_container",
    "verify_streaming",
]


@dataclass(frozen=True)
class PairingPayload:
    master_host: str
    master_port: int
    replication_user: str
    replication_password: str
    application_name: str


@dataclass(frozen=True)
class StepDescriptor:
    idx: int
    kind: StepKind
    title: str
    description: str


def list_steps(payload: PairingPayload) -> list[StepDescriptor]:
    return [
        StepDescriptor(
            idx=0,
            kind="stop_pg_container",
            title="Arrêter le conteneur Postgres local",
            description=(
                "On stoppe l'instance Postgres pour pouvoir remplacer son data dir. "
                "Si elle est en cours d'écriture, on attend la fin gracieuse."
            ),
        ),
        StepDescriptor(
            idx=1,
            kind="backup_pg_data_dir",
            title="Sauvegarder le data dir actuel",
            description=(
                "Le data dir actuel est renommé en .bak.<timestamp> pour permettre "
                "un rollback manuel si pg_basebackup échoue."
            ),
        ),
        StepDescriptor(
            idx=2,
            kind="pg_basebackup_from_master",
            title="pg_basebackup depuis le master",
            description=(
                f"Copie l'intégralité de la base du master ({payload.master_host}:"
                f"{payload.master_port}) en mode streaming, crée le slot de "
                f"réplication '{payload.application_name}'."
            ),
        ),
        StepDescriptor(
            idx=3,
            kind="verify_standby_signal",
            title="Vérifier standby.signal",
            description="Le fichier signal doit exister pour que Postgres démarre en mode standby.",
        ),
        StepDescriptor(
            idx=4,
            kind="verify_auto_conf",
            title="Vérifier postgresql.auto.conf",
            description="Doit contenir une ligne primary_conninfo=… avec le bon host/user.",
        ),
        StepDescriptor(
            idx=5,
            kind="start_pg_container",
            title="Démarrer le conteneur Postgres",
            description="Postgres démarre en mode standby (recovery).",
        ),
        StepDescriptor(
            idx=6,
            kind="verify_streaming",
            title="Vérifier le streaming WAL actif",
            description=(
                "Une ligne avec status='streaming' dans pg_stat_wal_receiver "
                "confirme que le WAL flux depuis le master."
            ),
        ),
    ]
