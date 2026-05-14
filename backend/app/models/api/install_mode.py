"""DTOs install_mode (LOT pairing-exec)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class InstallModeResponse(BaseModel):
    mode: Literal["docker_compose_auto", "native"]
    docker_socket_accessible: bool
    pg_container_data_host_path: str | None
