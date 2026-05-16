"""Middleware HTTP : transforme les exceptions de DB inaccessible en 503 propre.

Pendant le wizard pairing standby, Postgres est intentionnellement stoppé
entre `stop_pg_container` (step 1) et `start_pg_container` (step 7). Les
requêtes admin du frontend qui arrivent pendant ce temps (poll de status,
vérifications d'auth via JWT…) acquièrent le pool, tombent sur des
exceptions de connexion (`socket.gaierror`, `pool is closed`,
`InvalidPasswordError`…) et remontent en 500 avec un traceback complet
dans les logs — bruit énorme et signaux d'erreur trompeurs.

Ce middleware intercepte ces exceptions au niveau ASGI, retourne 503
`db_unavailable` avec `Retry-After: 5`, et log un structlog warning court
(pas error, pas traceback). Doit être enregistré comme middleware HTTP
**le plus externe** (donc après log_requests dans main.py).
"""

from __future__ import annotations

import socket
from collections.abc import Awaitable, Callable

import asyncpg.exceptions
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.logging import logger

# Exceptions signifiant "Postgres temporairement injoignable" — pas un bug
# applicatif. Cette liste doit rester restrictive pour ne pas masquer de
# vrais bugs derrière un 503 générique.
_DB_UNAVAILABLE_TYPES: tuple[type[BaseException], ...] = (
    socket.gaierror,
    ConnectionRefusedError,
    asyncpg.exceptions.InterfaceError,
    asyncpg.exceptions.InvalidPasswordError,
    asyncpg.exceptions.PostgresConnectionError,
)


def _unwrap_exception_group(exc: BaseException) -> BaseException:
    """Suit la chaîne d'ExceptionGroup pour atteindre l'erreur de fond.

    Starlette / anyio enveloppent les exceptions ASGI dans des BaseExceptionGroup
    imbriqués. Sans unwrap, un `isinstance(exc, socket.gaierror)` ne matche pas.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


async def db_availability_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """503 propre si la DB est temporairement injoignable, sinon re-raise."""
    try:
        return await call_next(request)
    except Exception as exc:
        actual = _unwrap_exception_group(exc)
        if not isinstance(actual, _DB_UNAVAILABLE_TYPES):
            raise
        logger.warning(
            "db_unavailable_during_request",
            path=request.url.path,
            method=request.method,
            error_type=type(actual).__name__,
            error=str(actual)[:200],
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "db_unavailable",
                "message": "Database temporarily unavailable. Retry shortly.",
            },
            headers={"Retry-After": "5"},
        )
