"""Moteur d'exécution Docker — pilote `harpocrate-postgres` via aiodocker.

Le path host du data dir Postgres est découvert au `open()` en inspectant les
bind mounts du conteneur. Aucune config admin nécessaire.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine

import aiodocker
import structlog

from app.services.pairing_exec.executor_base import Executor, StepResult
from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

logger = structlog.get_logger(__name__)

# Path attendu côté conteneur Postgres pour le data dir.
_PG_DATA_CONTAINER_PATH = "/var/lib/postgresql/data"


class DockerExecutor(Executor):
    def __init__(self, *, pg_container_name: str = "harpocrate-postgres") -> None:
        self._pg_container_name = pg_container_name
        self._docker: aiodocker.Docker | None = None
        self.pg_data_host_path: str | None = None

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
            "stop_pg_container": self._step_stop_pg,
            "backup_pg_data_dir": self._step_backup_data_dir,
            "pg_basebackup_from_master": self._step_pg_basebackup,
            "verify_standby_signal": self._step_verify_standby_signal,
            "verify_auto_conf": self._step_verify_auto_conf,
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

    async def _step_start_pg(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        await container.start()
        return StepResult(exit_code=0, stdout="container started", stderr="")

    async def _step_verify_streaming(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        sql = "SELECT pid, status, sender_host, sender_port FROM pg_stat_wal_receiver;"
        exec_inst = await container.exec(cmd=["psql", "-U", "postgres", "-At", "-c", sql])
        stream = exec_inst.start(detach=False)
        output_chunks: list[bytes] = []
        async with stream as s:
            async for msg in s:
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
