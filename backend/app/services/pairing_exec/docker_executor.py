"""Moteur d'exécution Docker — pilote `harpocrate-postgres` via aiodocker.

Le path host du data dir Postgres est découvert au `open()` en inspectant les
bind mounts du conteneur. Aucune config admin nécessaire.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine

import aiodocker
import structlog

from app.services.pairing_exec.executor_base import Executor, StepResult
from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

logger = structlog.get_logger(__name__)

# Path attendu côté conteneur Postgres pour le data dir.
_PG_DATA_CONTAINER_PATH = "/var/lib/postgresql/data"


class DockerExecutor(Executor):
    def __init__(
        self,
        *,
        pg_container_name: str = "harpocrate-postgres",
        pg_isready_timeout_seconds: int = 30,
    ) -> None:
        self._pg_container_name = pg_container_name
        self._docker: aiodocker.Docker | None = None
        self.pg_data_host_path: str | None = None
        self._pg_isready_timeout_seconds = pg_isready_timeout_seconds

    async def open(self) -> None:
        if self._docker is not None:
            return
        self._docker = aiodocker.Docker()
        container = await self._docker.containers.get(self._pg_container_name)
        info = await container.show()
        for mount in info.get("Mounts", []):
            if mount.get("Destination") == _PG_DATA_CONTAINER_PATH:
                self.pg_data_host_path = mount["Source"]
                break
        if self.pg_data_host_path is None:
            raise RuntimeError("pg_data_mount_not_found")
        logger.info(
            "docker_executor_opened",
            pg_container=self._pg_container_name,
            pg_data_host_path=self.pg_data_host_path,
        )

    async def close(self) -> None:
        if self._docker is not None:
            await self._docker.close()
            self._docker = None

    async def exec_step(self, step: StepDescriptor, payload: PairingPayload) -> StepResult:
        if self._docker is None or self.pg_data_host_path is None:
            raise RuntimeError("executor_not_opened")

        dispatcher: dict[str, object] = {
            "verify_master_reachable": self._step_verify_master_reachable,
            "stop_pg_container": self._step_stop_pg,
            "backup_pg_data_dir": self._step_backup_data_dir,
            "pg_basebackup_from_master": self._step_pg_basebackup,
            "verify_standby_signal": self._step_verify_standby_signal,
            "verify_auto_conf": self._step_verify_auto_conf,
            "write_db_credentials_override": self._step_write_db_credentials_override,
            "start_pg_container": self._step_start_pg,
            "verify_streaming": self._step_verify_streaming,
        }
        handler = dispatcher.get(step.kind)
        if handler is None:
            return StepResult(
                exit_code=99,
                stdout="",
                stderr=f"unknown_step_kind:{step.kind}",
            )
        typed_handler: Callable[[PairingPayload], Coroutine[object, object, StepResult]]
        typed_handler = handler  # type: ignore[assignment]
        return await typed_handler(payload)

    # ------------------------------------------------------------------
    # Handlers privés — un par kind
    # ------------------------------------------------------------------

    async def _step_verify_master_reachable(self, payload: PairingPayload) -> StepResult:
        """Pré-vérif non destructive : pg_isready depuis un conteneur éphémère.

        Si le master n'est pas joignable (firewall, port fermé, master down),
        ce step échoue AVANT que `stop_pg_container` ne touche au standby.
        Le data dir local reste intact, l'admin peut retry après avoir
        corrigé la conf master.
        """
        cmd = [
            "pg_isready",
            "-h", payload.master_host,
            "-p", str(payload.master_port),
            "-U", payload.replication_user,
            "-t", "5",
        ]
        return await self._run_ephemeral(
            image="postgres:16-alpine",
            cmd=cmd,
            binds=[],
        )

    async def _step_stop_pg(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        await container.stop(timeout=30)
        return StepResult(exit_code=0, stdout="container stopped", stderr="")

    async def _step_backup_data_dir(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None and self.pg_data_host_path is not None
        parent_dir, leaf = self._parent_and_leaf()
        cmd = f"mv /host/{leaf} /host/{leaf}.bak.$(date +%s)"
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", cmd],
            binds=[f"{parent_dir}:/host"],
        )

    async def _step_pg_basebackup(self, payload: PairingPayload) -> StepResult:
        assert self.pg_data_host_path is not None
        parent_dir, leaf = self._parent_and_leaf()
        env = {"PGPASSWORD": payload.replication_password}
        bb = (
            f"pg_basebackup -h {payload.master_host} -p {payload.master_port} "
            f"-D /host/{leaf} -U {payload.replication_user} "
            f"--slot={payload.application_name} -R --wal-method=stream"
        )
        return await self._run_ephemeral(
            image="postgres:16-alpine",
            cmd=["sh", "-c", bb],
            binds=[f"{parent_dir}:/host"],
            env=env,
        )

    async def _step_verify_standby_signal(self, payload: PairingPayload) -> StepResult:
        assert self.pg_data_host_path is not None
        parent_dir, leaf = self._parent_and_leaf()
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", f"test -f /host/{leaf}/standby.signal && echo present"],
            binds=[f"{parent_dir}:/host:ro"],
        )

    async def _step_verify_auto_conf(self, payload: PairingPayload) -> StepResult:
        assert self.pg_data_host_path is not None
        parent_dir, leaf = self._parent_and_leaf()
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", f"grep primary_conninfo /host/{leaf}/postgresql.auto.conf"],
            binds=[f"{parent_dir}:/host:ro"],
        )

    async def _step_write_db_credentials_override(self, payload: PairingPayload) -> StepResult:
        """Écrit le password Postgres du master dans le fichier override.

        Le fichier est créé dans le dossier PARENT du data dir Postgres :
        si le data dir host est `/opt/harpocrate/data/postgres`, le fichier
        sera `/opt/harpocrate/data/db-password-override.txt`. C'est le path
        que le compose bind-mount vers `/var/lib/harpocrate/db-password-override.txt`
        dans le conteneur backend.

        Le password est passé via env var au conteneur éphémère (pas via la
        commande shell) pour éviter les soucis d'escape avec les chars
        spéciaux dans le password.
        """
        if not payload.master_postgres_password:
            return StepResult(
                exit_code=1,
                stdout="",
                stderr="master_postgres_password absent du payload pairing",
            )
        assert self.pg_data_host_path is not None
        parent_dir, _leaf = self._parent_and_leaf()
        # `printf '%s'` évite le trailing newline que `echo` ajoute par défaut.
        cmd_sh = "printf '%s' \"$DB_PASSWORD\" > /host/db-password-override.txt"
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", cmd_sh],
            binds=[f"{parent_dir}:/host"],
            env={"DB_PASSWORD": payload.master_postgres_password},
        )

    async def _step_start_pg(self, payload: PairingPayload) -> StepResult:
        """Démarre le conteneur Postgres et attend qu'il accepte les connexions.

        `container.start()` retourne dès que le process Postgres est lancé par
        Docker, PAS quand Postgres est prêt à accepter des connexions. Sans
        attendre `pg_isready`, le step suivant (`verify_streaming`) ouvre une
        connexion `psql` au socket Unix qui n'existe pas encore et échoue.
        """
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        await container.start()
        for _ in range(self._pg_isready_timeout_seconds):
            if await self._exec_pg_isready(container):
                return StepResult(
                    exit_code=0,
                    stdout="container started and ready",
                    stderr="",
                )
            await asyncio.sleep(1)
        return StepResult(
            exit_code=1,
            stdout="",
            stderr=(
                f"timeout waiting for pg_isready after "
                f"{self._pg_isready_timeout_seconds}s"
            ),
        )

    async def _exec_pg_isready(self, container: object) -> bool:
        """Retourne True si `pg_isready` répond OK dans le conteneur Postgres.

        Utilise `$POSTGRES_USER` (env var du conteneur Postgres) pour le
        startup packet. Hardcoder `-U postgres` est faux : avec
        `POSTGRES_USER=harpocrate` (cas standard de la stack), le role
        `postgres` n'existe pas dans `pg_authid` et `pg_isready` retourne
        exit_code 1 (rejected) — la boucle ne sort jamais et le step finit
        en timeout au lieu de step_done.
        """
        exec_inst = await container.exec(  # type: ignore[attr-defined]
            cmd=[
                "sh", "-c",
                'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q',
            ],
        )
        async with exec_inst.start(detach=False) as stream:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
        info = await exec_inst.inspect()
        exit_code = info.get("ExitCode")
        if exit_code is None:
            return False
        return int(exit_code) == 0

    async def _step_verify_streaming(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        sql = "SELECT pid, status, sender_host, sender_port FROM pg_stat_wal_receiver;"
        exec_inst = await container.exec(cmd=["psql", "-U", "postgres", "-At", "-c", sql])
        output_chunks: list[bytes] = []
        # aiodocker Stream n'expose pas __aiter__ : on consomme via read_out()
        # dans une boucle jusqu'à recevoir None (fin du flux).
        async with exec_inst.start(detach=False) as stream:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                if msg.data:
                    output_chunks.append(msg.data)
        info = await exec_inst.inspect()
        exit_code = int(info.get("ExitCode", 1) or 0)
        stdout = b"".join(output_chunks).decode("utf-8", errors="replace")
        if exit_code == 0 and "streaming" not in stdout:
            return StepResult(exit_code=2, stdout=stdout, stderr="status not streaming")
        return StepResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr="" if exit_code == 0 else stdout,
        )

    # ------------------------------------------------------------------
    # Helpers partagés
    # ------------------------------------------------------------------

    def _parent_and_leaf(self) -> tuple[str, str]:
        assert self.pg_data_host_path is not None
        path = self.pg_data_host_path.rstrip("/")
        leaf = path.split("/")[-1]
        parent = "/".join(path.split("/")[:-1]) or "/"
        return parent, leaf

    async def _run_ephemeral(
        self,
        *,
        image: str,
        cmd: list[str],
        binds: list[str],
        env: dict[str, str] | None = None,
    ) -> StepResult:
        assert self._docker is not None
        config = {
            "Image": image,
            "Cmd": cmd,
            "Env": [f"{k}={v}" for k, v in (env or {}).items()],
            "HostConfig": {"Binds": binds, "AutoRemove": False},
        }
        container = await self._docker.containers.run(config=config)
        wait = await container.wait()
        exit_code = int(wait.get("StatusCode", 1))
        logs = await container.log(stdout=True, stderr=True)
        stdout = "".join(logs) if isinstance(logs, list) else str(logs)
        await container.delete(force=True)
        return StepResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr="" if exit_code == 0 else stdout,
        )
