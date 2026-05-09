"""Endpoints CRUD des environnements de wallet par-user (LOT_58)."""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.core.security import JwtUser
from app.db.pool import get_pool
from app.db.repositories import users as users_repo
from app.db.repositories import wallet_environments as repo

router = APIRouter(prefix="/me/wallet-environments", tags=["me-wallet-environments"])


async def _resolve_user_id(current_user: JwtUser) -> UUID:
    """Trouve l'UUID Harpocrate du user courant via son keycloak_sub.
    Lève 404 first_login si pas encore bootstrappé."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_id = await users_repo.get_id_by_keycloak_sub(
            conn, current_user.keycloak_sub
        )
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "first_login",
                "message": "User must complete bootstrap before using environments",
            },
        )
    return user_id


@router.get("")
async def list_environments(current_user: JwtUser) -> JSONResponse:
    """Liste les environnements de l'utilisateur. NE renvoie PAS l'item
    virtuel "None" (responsabilité du frontend qui l'affiche en tête)."""
    user_id = await _resolve_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        envs = await repo.list_for_user(conn, user_id)
    return JSONResponse(
        {
            "environments": [
                {
                    "id": str(e.id),
                    "name": e.name,
                    "created_at": e.created_at.isoformat(),
                }
                for e in envs
            ]
        }
    )


class CreateEnvironmentBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_environment(
    body: CreateEnvironmentBody,
    current_user: JwtUser,
) -> JSONResponse:
    user_id = await _resolve_user_id(current_user)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "name_empty", "message": "name must not be empty"},
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_id = await repo.create(conn, owner_user_id=user_id, name=name)
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "name_already_exists",
                    "message": f"environment '{name}' already exists",
                },
            ) from exc
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(new_id), "name": name},
    )


@router.delete(
    "/{env_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_environment(env_id: UUID, current_user: JwtUser) -> Response:
    user_id = await _resolve_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Vérifie d'abord qu'il n'est pas utilisé (UX > erreur SQL brute).
        usage = await repo.count_wallets_using(conn, env_id)
        if usage > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "environment_in_use",
                    "message": f"{usage} wallet(s) still reference this environment",
                },
            )
        try:
            ok = await repo.delete(conn, env_id=env_id, owner_user_id=user_id)
        except asyncpg.ForeignKeyViolationError as exc:
            # Filet de sécurité si une race a inséré un wallet entre temps.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "environment_in_use"},
            ) from exc
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "environment_not_found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
