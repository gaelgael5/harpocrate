"""Moteur d'exécution natif via SSH (asyncssh).

Une session SSH unique est ouverte pour toute la durée du wizard. Toutes les
commandes (docker stop/start/exec si l'admin a Docker côté hôte, ou bien
systemctl + pg_basebackup natif sinon) sont exécutées via `conn.run(...)`.

Pour l'itération 1 du LOT, on cible le scénario « Docker côté hôte » :
l'admin a Docker installé sur sa machine, mais Harpocrate n'a pas le socket
monté → on bascule en SSH. Les commandes restent les mêmes que DockerExecutor
mais sont des invocations shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncssh
import structlog

from app.services.pairing_exec.executor_base import Executor, StepResult
from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SshCredentials:
    host: str
    port: int
    username: str
    password: str | None
    private_key: str | None
    passphrase: str | None


class NativeSshExecutor(Executor):
    def __init__(
        self, creds: SshCredentials, *, pg_container_name: str = "harpocrate-postgres"
    ) -> None:
        self._creds = creds
        self._pg_container = pg_container_name
        self._conn: Any | None = None

    async def open(self) -> None:
        if self._conn is not None:
            return
        kwargs: dict[str, Any] = {
            "host": self._creds.host,
            "port": self._creds.port,
            "username": self._creds.username,
            "known_hosts": None,  # TOFU MVP — voir LESSONS pour le durcissement
        }
        if self._creds.private_key:
            kwargs["client_keys"] = [
                asyncssh.import_private_key(
                    self._creds.private_key,
                    passphrase=self._creds.passphrase or None,
                )
            ]
        elif self._creds.password:
            kwargs["password"] = self._creds.password
        self._conn = await asyncssh.connect(**kwargs)
        logger.warning(
            "native_ssh_executor_opened_tofu",
            host=self._creds.host,
            note="known_hosts disabled (MVP) — strengthen before production",
        )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def exec_step(self, step: StepDescriptor, payload: PairingPayload) -> StepResult:
        if self._conn is None:
            raise RuntimeError("executor_not_opened")
        cmd = _build_command(step, payload, self._pg_container)
        result = await self._conn.run(cmd, check=False)
        return StepResult(
            exit_code=int(result.exit_status or 0),
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
        )


def _build_command(step: StepDescriptor, payload: PairingPayload, pg_container: str) -> str:
    pg_data = "/var/lib/postgresql/16/data"
    if step.kind == "stop_pg_container":
        return f"docker stop {pg_container}"
    if step.kind == "backup_pg_data_dir":
        return f"sudo mv {pg_data} {pg_data}.bak.$(date +%s)"
    if step.kind == "pg_basebackup_from_master":
        return (
            f"PGPASSWORD='{payload.replication_password}' sudo -E -u postgres "
            f"pg_basebackup -h {payload.master_host} -p {payload.master_port} "
            f"-D {pg_data} -U {payload.replication_user} "
            f"--slot={payload.application_name} -R --wal-method=stream"
        )
    if step.kind == "verify_standby_signal":
        return f"sudo -u postgres test -f {pg_data}/standby.signal && echo present"
    if step.kind == "verify_auto_conf":
        return f"sudo -u postgres grep primary_conninfo {pg_data}/postgresql.auto.conf"
    if step.kind == "start_pg_container":
        return f"docker start {pg_container}"
    if step.kind == "verify_streaming":
        return (
            f"docker exec {pg_container} psql -U postgres -At -c "
            f"'SELECT pid, status FROM pg_stat_wal_receiver;'"
        )
    return f"echo unknown_step_kind:{step.kind} >&2; exit 99"
