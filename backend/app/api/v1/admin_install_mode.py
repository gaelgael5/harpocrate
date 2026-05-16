"""Endpoint REST exposant le mode d'installation détecté (LOT pairing-exec)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.admin_auth import AdminJwt
from app.models.api.install_mode import InstallModeResponse
from app.services import install_mode as svc

router = APIRouter(prefix="/admin", tags=["admin-install-mode"])


@router.get("/install-mode", response_model=InstallModeResponse)
async def get_install_mode(admin: AdminJwt) -> InstallModeResponse:
    info = svc.detect()
    return InstallModeResponse(
        mode=info.mode,
        docker_socket_accessible=info.docker_socket_accessible,
        pg_container_data_host_path=info.pg_container_data_host_path,
    )
