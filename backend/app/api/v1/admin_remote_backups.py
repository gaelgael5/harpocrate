"""Endpoints admin /v1/admin/backup-remotes — gestion des connexions de backup distantes.

Auth : AdminJwt uniquement (rôle Keycloak `harpocrate-admin`).
Sécurité : les credentials ne sont JAMAIS retournés dans aucune réponse HTTP.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.services import remote_backup_connections as svc
from app.services.remote_backup_providers import (
    SUPPORTED_KINDS as _ALLOWED_KINDS,
)
from app.services.remote_backup_providers import (
    RemoteBackupProviderError,
    get_provider,
)

router = APIRouter(prefix="/admin/backup-remotes", tags=["admin-remote-backups"])

# ─── Models ──────────────────────────────────────────────────────────────────


class RemoteBackupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str
    config: dict[str, Any]
    credentials: dict[str, Any]

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in _ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {sorted(_ALLOWED_KINDS)}")
        return v


class RemoteBackupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_class=JSONResponse)
async def list_remote_backups(admin: AdminJwt) -> JSONResponse:
    """Liste toutes les connexions actives (sans credentials)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        items = await svc.list_connections(conn)
    return JSONResponse({"connections": [c.to_dict() for c in items]})


@router.post("", status_code=status.HTTP_201_CREATED, response_class=JSONResponse)
async def create_remote_backup(body: RemoteBackupCreate, admin: AdminJwt) -> JSONResponse:
    """Crée une nouvelle connexion. Les credentials sont chiffrés avant insertion."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_id = await svc.create_connection(
                conn,
                name=body.name,
                kind=body.kind,
                config=body.config,
                credentials=body.credentials,
                created_by_user_id=None,  # admin JWT n'a pas de user DB id (pas bootstrappé)
            )
        except Exception as exc:
            msg = str(exc)
            if "unique" in msg.lower() or "23505" in msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "name_already_exists"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": msg},
            ) from exc
    return JSONResponse({"id": str(new_id)}, status_code=status.HTTP_201_CREATED)


@router.get("/{connection_id}", response_class=JSONResponse)
async def get_remote_backup(connection_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Détail d'une connexion (sans credentials)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_connection(conn, connection_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "connection_not_found"},
        )
    return JSONResponse(item.to_dict())


@router.patch("/{connection_id}", response_class=JSONResponse)
async def update_remote_backup(
    connection_id: UUID, body: RemoteBackupUpdate, admin: AdminJwt
) -> JSONResponse:
    """Update partiel : name, config, credentials. Les champs None sont ignorés."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await svc.get_connection(conn, connection_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found"},
            )
        affected = await svc.update_connection(
            conn,
            connection_id=connection_id,
            name=body.name,
            config=body.config,
            credentials=body.credentials,
        )
    return JSONResponse({"updated": affected})


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_remote_backup(connection_id: UUID, admin: AdminJwt) -> Response:
    """Soft-delete (deleted_at = NOW)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        affected = await svc.delete_connection(conn, connection_id)
    if affected == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "connection_not_found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connection_id}/test", response_class=JSONResponse)
async def test_remote_backup(connection_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Teste la connexion : ouvre une connexion SFTP, vérifie l'accès au remote_path, ferme."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_connection(conn, connection_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found"},
            )
        creds = await svc.get_decrypted_credentials(conn, connection_id)
    if creds is None:  # pragma: no cover — déjà filtré juste avant
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "connection_not_found"},
        )

    provider = get_provider(item.kind, item.config, creds)
    try:
        await provider.test_connection()
    except RemoteBackupProviderError as exc:
        return JSONResponse(
            {"ok": False, "error": "test_failed", "message": str(exc)},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    return JSONResponse({"ok": True})
