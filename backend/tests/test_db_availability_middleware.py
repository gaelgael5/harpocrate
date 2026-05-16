"""Tests db_availability_middleware.

Pendant le wizard pairing standby, Postgres est intentionnellement stoppé
entre step 1 et step 7. Les requêtes qui arrivent pendant ce temps tombaient
sur des exceptions non gérées (`socket.gaierror`, `pool is closed`, etc.),
remontaient en 500 avec traceback complet — bruit énorme.

Ce middleware les transforme en 503 propre avec un log structlog warning
court (pas error, pas traceback).
"""

from __future__ import annotations

import base64
import socket
from typing import Any
from unittest.mock import AsyncMock

import asyncpg.exceptions
import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _make_request(path: str = "/v1/admin/foo") -> Any:
    """Mock minimaliste d'une Request Starlette pour le middleware."""
    from starlette.datastructures import URL

    req = AsyncMock()
    req.url = URL(f"http://test{path}")
    req.method = "GET"
    return req


@pytest.mark.asyncio
async def test_middleware_passes_through_normal_response() -> None:
    """Sans exception, le middleware retourne la réponse de call_next telle quelle."""
    from fastapi.responses import JSONResponse

    from app.middleware.db_availability import db_availability_middleware

    expected = JSONResponse(content={"ok": True}, status_code=200)

    async def call_next(_req: object) -> object:
        return expected

    result = await db_availability_middleware(_make_request(), call_next)
    assert result is expected


@pytest.mark.asyncio
async def test_middleware_converts_socket_gaierror_to_503() -> None:
    """socket.gaierror (DNS Postgres absent) → 503 db_unavailable."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        raise socket.gaierror(-2, "Name or service not known")

    response = await db_availability_middleware(_make_request(), call_next)
    assert response.status_code == 503
    assert response.headers.get("retry-after") == "5"
    body = response.body.decode()
    assert "db_unavailable" in body


@pytest.mark.asyncio
async def test_middleware_converts_connection_refused_to_503() -> None:
    """ConnectionRefusedError (port fermé) → 503 db_unavailable."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        raise ConnectionRefusedError(111, "Connection refused")

    response = await db_availability_middleware(_make_request(), call_next)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_middleware_converts_asyncpg_interface_error_to_503() -> None:
    """asyncpg.InterfaceError 'pool is closed' → 503 db_unavailable."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        raise asyncpg.exceptions.InterfaceError("pool is closed")

    response = await db_availability_middleware(_make_request(), call_next)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_middleware_converts_asyncpg_invalid_password_to_503() -> None:
    """InvalidPasswordError pendant transition pairing → 503 db_unavailable."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        raise asyncpg.exceptions.InvalidPasswordError(
            "password authentication failed for user 'harpocrate'"
        )

    response = await db_availability_middleware(_make_request(), call_next)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_middleware_unwraps_exception_group() -> None:
    """Starlette enveloppe les exceptions ASGI dans ExceptionGroup → unwrap pour matcher."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        inner = socket.gaierror(-2, "Name or service not known")
        raise BaseExceptionGroup("ASGI", [inner])

    response = await db_availability_middleware(_make_request(), call_next)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_middleware_reraises_unrelated_exception() -> None:
    """Pour toute autre exception (bug applicatif), on re-raise — pas de masquage."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        raise ValueError("bug applicatif")

    with pytest.raises(ValueError, match="bug applicatif"):
        await db_availability_middleware(_make_request(), call_next)


@pytest.mark.asyncio
async def test_middleware_reraises_unrelated_inside_exception_group() -> None:
    """Un ValueError dans un ExceptionGroup doit aussi être re-raise (pas matcher)."""
    from app.middleware.db_availability import db_availability_middleware

    async def call_next(_req: object) -> object:
        raise BaseExceptionGroup("X", [ValueError("bug")])

    with pytest.raises(BaseExceptionGroup):
        await db_availability_middleware(_make_request(), call_next)
