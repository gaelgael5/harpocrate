"""Moteur d'exécution Docker — pilote `harpocrate-postgres` via aiodocker.

Le path host du data dir Postgres est découvert au `open()` en inspectant les
bind mounts du conteneur. Aucune config admin nécessaire.
"""

from __future__ import annotations

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
        # Implémentation complète Task 6.
        raise NotImplementedError(f"step_kind_not_yet_implemented:{step.kind}")
