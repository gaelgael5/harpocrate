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
from app.db.repositories import oauth_pending_session as oauth_repo
from app.services import gdrive_oauth_session as gdrive_svc
from app.services import remote_backup_connections as svc
from app.services.audit import audit_log_insert
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
    oauth_state: str | None = None  # requis quand kind='gdrive'

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


class RemoteBackupTestNew(BaseModel):
    """Body pour tester un path avec credentials fournis (création / nouveaux creds)."""

    kind: str
    config: dict[str, Any]
    credentials: dict[str, Any]
    path: str = Field(min_length=1)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in _ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {sorted(_ALLOWED_KINDS)}")
        return v


class RemoteBackupTestStored(BaseModel):
    """Body pour tester un path en réutilisant les credentials stockés en DB.

    Pratique en édition : l'admin n'a pas resaisi les creds (zero-knowledge —
    on ne les ré-affiche jamais), mais veut tester un nouveau path. Le `config`
    optionnel permet aussi de tester un host modifié sans avoir à sauver d'abord.
    """

    path: str = Field(min_length=1)
    config: dict[str, Any] | None = None


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
    """Crée une nouvelle connexion. Les credentials sont chiffrés avant insertion.

    Pour kind='gdrive', consomme une oauth_pending_session autorisée : body.oauth_state
    est obligatoire, et config/credentials sont hydratés depuis la session (le body
    config/credentials fourni est ignoré).
    """
    pool = await get_pool()

    # ── Branche gdrive : consomme une oauth_pending_session authorized ──────────
    if body.kind == "gdrive":
        if not body.oauth_state:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "oauth_state_required_for_gdrive"},
            )
        async with pool.acquire() as conn:
            pending = await oauth_repo.get_by_state(conn, body.oauth_state)
            if pending is None or pending["status"] != "authorized":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "oauth_session_not_authorized"},
                )
            payload = dict(pending["payload"])
            result = dict(pending["result"] or {})

            target_id = pending["target_connection_id"]
            cfg = {
                "client_id": payload["client_id"],
                "redirect_uri": payload["redirect_uri"],
                "folder_name": payload["folder_name"],
                "user_email": result.get("user_email", ""),
            }
            creds = {
                "client_secret": payload["client_secret"],
                "refresh_token": result["refresh_token"],
                "scope": "https://www.googleapis.com/auth/drive.file",
                "token_uri": result.get("token_uri", "https://oauth2.googleapis.com/token"),
            }
            try:
                if target_id is None:
                    new_id = await svc.create_connection(
                        conn,
                        name=body.name,
                        kind="gdrive",
                        config=cfg,
                        credentials=creds,
                        created_by_user_id=None,
                    )
                else:
                    await svc.update_connection(
                        conn,
                        connection_id=target_id,
                        name=None,
                        config=cfg,
                        credentials=creds,
                    )
                    new_id = target_id
                await oauth_repo.delete_by_state(conn, body.oauth_state)
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

    # ── Branche existante (sftp / s3 / ftps) — inchangée ────────────────────────
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


@router.post("/{connection_id}/reauthorize", response_class=JSONResponse)
async def reauthorize_remote_backup(connection_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Relance un flow OAuth pour une connexion gdrive existante (token révoqué).

    Récupère client_id / client_secret / redirect_uri / folder_name de la connexion
    existante et crée une nouvelle oauth_pending_session avec target_connection_id=id.
    Retourne {auth_url, state}.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_connection(conn, connection_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found"},
            )
        if item.kind != "gdrive":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "reauthorize_unsupported_kind", "kind": item.kind},
            )
        cfg = item.config
        existing_creds = await svc.get_decrypted_credentials(conn, connection_id)
        if existing_creds is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "no_existing_credentials"},
            )
        out = await gdrive_svc.create_pending_session(
            conn,
            name=item.name,
            client_id=cfg["client_id"],
            client_secret=existing_creds["client_secret"],
            folder_name=cfg["folder_name"],
            redirect_uri=cfg["redirect_uri"],
            target_connection_id=connection_id,
            created_by_user_id=None,
        )
        await audit_log_insert(
            conn,
            "remote_backup.gdrive.reauthorized",
            actor_user_id=None,
            metadata={
                "connection_id": str(connection_id),
                "connection_name": item.name,
            },
        )
    return JSONResponse(out)


def _test_response(
    ok: bool,
    error: str | None = None,
    message: str | None = None,
    config_patch: dict[str, Any] | None = None,
) -> JSONResponse:
    """Helper — wrap les retours du test en 200 (jamais 5xx).

    Pourquoi 200 systématique :
      - sémantiquement la requête HTTP a abouti, le résultat (positif ou
        négatif) est dans le body : c'est un payload, pas une erreur transport
      - Cloudflare avale les 5xx et affiche sa page générique, masquant le
        message d'erreur du provider que l'admin a besoin de voir
    """
    body: dict[str, Any] = {"ok": ok}
    if not ok:
        body["error"] = error or "test_failed"
        body["message"] = message or ""
    if config_patch:
        body["config_patch"] = config_patch
    return JSONResponse(body, status_code=status.HTTP_200_OK)


@router.post("/test", response_class=JSONResponse)
async def test_remote_backup_with_provided_creds(
    body: RemoteBackupTestNew, admin: AdminJwt
) -> JSONResponse:
    """Teste un path avec config + creds fournis dans le body.

    Usage : création d'une connexion (avant sauvegarde), ou édition après
    resaisie des credentials. Aucun accès DB — tout vient du body.
    """
    try:
        provider = get_provider(body.kind, body.config, body.credentials)
    except ValueError as exc:
        return _test_response(False, error="invalid_config", message=str(exc))

    try:
        patch_out = await provider.test_connection(body.path)
    except RemoteBackupProviderError as exc:
        return _test_response(False, error="test_failed", message=str(exc))
    return _test_response(True, config_patch=patch_out)


@router.post("/{connection_id}/test", response_class=JSONResponse)
async def test_remote_backup_with_stored_creds(
    connection_id: UUID, body: RemoteBackupTestStored, admin: AdminJwt
) -> JSONResponse:
    """Teste un path avec creds stockés en DB. Le `config` peut être surchargé.

    Usage : édition d'une connexion existante (creds non resaisis car
    zero-knowledge), test d'un path avec ou sans modif du config.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_connection(conn, connection_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found"},
            )
        creds = await svc.get_decrypted_credentials(conn, connection_id)
    if creds is None:
        return _test_response(
            False,
            error="no_credentials",
            message="Connection has no stored credentials. Save credentials first.",
        )

    config_to_use = body.config if body.config is not None else item.config
    try:
        provider = get_provider(item.kind, config_to_use, creds)
    except ValueError as exc:
        return _test_response(False, error="invalid_config", message=str(exc))

    try:
        patch_out = await provider.test_connection(body.path)
    except RemoteBackupProviderError as exc:
        return _test_response(False, error="test_failed", message=str(exc))

    # Persiste le patch en DB si non-vide (cas Drive : folder_id découvert).
    if patch_out:
        async with pool.acquire() as conn:
            merged = {**item.config, **patch_out}
            await svc.update_connection(
                conn,
                connection_id=connection_id,
                name=None,
                config=merged,
                credentials=None,
            )
    return _test_response(True, config_patch=patch_out)
