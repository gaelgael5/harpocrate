"""Génération de la liste ordonnée des commandes pour transformer un host en
standby Postgres d'un master donné (LOT 3).

Les commandes sont AFFICHÉES à l'admin pour copier-coller dans son SSH.
Harpocrate n'exécute rien lui-même.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WizardStep:
    """Une étape du wizard d'appairage.

    `idx` : position 0-indexed.
    `title` : libellé court affiché dans le stepper Mantine.
    `command` : commande shell à coller dans la session SSH de l'admin.
    `hint` : explication ou critère de succès. Vide si rien à dire.
    """

    idx: int
    title: str
    command: str
    hint: str = ""


def build_standby_steps(
    *,
    master_host: str,
    master_port: int,
    replication_user: str,
    replication_password: str,
    application_name: str,
    container_name: str = "harpocrate-postgres",
    pg_data_dir: str = "/var/lib/postgresql/16/data",
) -> list[WizardStep]:
    """Construit la liste ordonnée des étapes pour transformer cette instance
    Postgres (locale, dans un conteneur Docker) en standby asynchrone du master
    décrit par les arguments.

    Le mot de passe replication est inclus en clair dans la commande
    pg_basebackup via PGPASSWORD — c'est acceptable car la session SSH appartient
    à l'admin et n'est jamais persistée (Harpocrate ne l'exécute pas).
    """
    bb_cmd = (
        f"PGPASSWORD='{replication_password}' "
        f"sudo -E -u postgres pg_basebackup "
        f"-h {master_host} -p {master_port} "
        f"-D {pg_data_dir} -U {replication_user} "
        f"-P --slot={application_name} -R --wal-method=stream"
    )
    return [
        WizardStep(
            0,
            "Arrêter le conteneur Postgres local",
            f"docker stop {container_name}",
            "Le conteneur doit être stoppé avant de remplacer le data dir.",
        ),
        WizardStep(
            1,
            "Sauvegarder le data dir actuel",
            f"sudo mv {pg_data_dir} {pg_data_dir}.bak.$(date +%s)",
            "On garde l'ancien data dir au cas où — à supprimer plus tard.",
        ),
        WizardStep(
            2,
            "Lancer pg_basebackup depuis le master",
            bb_cmd,
            "Cette étape peut prendre plusieurs minutes selon la taille de la base.",
        ),
        WizardStep(
            3,
            "Vérifier la présence de standby.signal",
            f"sudo -u postgres ls {pg_data_dir}/standby.signal",
            "Doit afficher le chemin complet — sinon pg_basebackup -R a échoué.",
        ),
        WizardStep(
            4,
            "Vérifier postgresql.auto.conf",
            f"sudo -u postgres cat {pg_data_dir}/postgresql.auto.conf",
            "Doit contenir une ligne primary_conninfo=… avec le bon host/user.",
        ),
        WizardStep(
            5,
            "Démarrer le conteneur Postgres",
            f"docker start {container_name}",
            "Démarre Postgres en mode standby.",
        ),
        WizardStep(
            6,
            "Vérifier le mode recovery",
            (f"docker exec {container_name} psql -U postgres -c 'SELECT pg_is_in_recovery();'"),
            "Attendu : t (true) — l'instance est bien en standby.",
        ),
        WizardStep(
            7,
            "Vérifier le streaming WAL actif",
            (
                f"docker exec {container_name} psql -U postgres "
                "-c 'SELECT pid, status, sender_host, sender_port "
                "FROM pg_stat_wal_receiver;'"
            ),
            "Une ligne avec status='streaming' confirme que le WAL flux depuis A.",
        ),
    ]
