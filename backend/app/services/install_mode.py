"""Détection du mode d'installation Harpocrate.

`docker_compose_auto` : conteneur Docker (présence de /.dockerenv) AVEC socket
Docker monté (typiquement /var/run/docker.sock) → on peut piloter `docker stop`,
`docker run`, `docker exec` depuis le backend via aiodocker.

`native` : tout autre cas. Le pilotage de Postgres nécessitera une session SSH
avec credentials saisies par l'admin.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

InstallMode = Literal["docker_compose_auto", "native"]


@dataclass(frozen=True)
class InstallModeInfo:
    mode: InstallMode
    docker_socket_accessible: bool
    pg_container_data_host_path: str | None


def detect(
    *,
    root_path: Path = Path("/"),
    docker_socket_path: Path = Path("/var/run/docker.sock"),
) -> InstallModeInfo:
    in_container = (root_path / ".dockerenv").exists()
    socket_ok = docker_socket_path.exists()
    if in_container and socket_ok:
        return InstallModeInfo(
            mode="docker_compose_auto",
            docker_socket_accessible=True,
            pg_container_data_host_path=None,
        )
    return InstallModeInfo(
        mode="native",
        docker_socket_accessible=False,
        pg_container_data_host_path=None,
    )
