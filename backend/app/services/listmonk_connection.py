"""Connexion Listmonk paramétrée en base (épic « Cultures et templates Listmonk
paramétrés en base », feature 3).

RÈGLE DE SÉCURITÉ : le token ne sort jamais de ce module autrement que sous `SecretStr`,
déballé au seul point d'usage (en-tête Authorization). Il n'apparaît dans aucune réponse
d'API, aucun log, aucune ligne d'audit.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
import httpx
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException, status
from pydantic import BaseModel, SecretStr

from app.core import server_secret_box
from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import listmonk_connection as repo
from app.models.db.listmonk_connection import ListmonkConnection, ListmonkConnectionView
from app.services.audit import audit_log_insert

# `purpose` HKDF propre au token Listmonk : changer cette valeur rend illisibles les
# tokens déjà stockés.
_TOKEN_PURPOSE = b"harpocrate.listmonk.token.v1"
MAX_URL_LENGTH = 2048
_TEST_TIMEOUT_SECONDS = 5.0


class InvalidListmonkUrlError(ValueError):
    """URL refusée (ValueError : Pydantic la rend en 422)."""


class ConnectionTestResult(BaseModel):
    ok: bool
    # Code HTTP de Listmonk, ou None si le serveur n'a pas été joint.
    http_status: int | None


def validate_listmonk_url(url: str) -> str:
    """Valide l'URL de base de Listmonk et la renvoie sans `/` final.

    HTTP en clair reste accepté : Listmonk est le plus souvent joint sur le réseau local
    de l'hôte (ex. `http://mail.home.lan:9000`). Pas d'identifiants dans l'URL : ils
    s'afficheraient dans l'IHM et les journaux, le token a son propre champ chiffré.
    """
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() for c in url):
        raise InvalidListmonkUrlError("url is empty, too long or contains spaces")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidListmonkUrlError("url must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise InvalidListmonkUrlError("url must not embed credentials")
    if parts.query or parts.fragment:
        raise InvalidListmonkUrlError("url must not contain a query or a fragment")
    try:
        _ = parts.port
    except ValueError as exc:
        raise InvalidListmonkUrlError("url has an invalid port") from exc
    return url.rstrip("/")


def auth_header(connection: ListmonkConnection) -> str:
    # Point d'usage unique du token en clair.
    return f"token {connection.api_user}:{connection.token.get_secret_value()}"


async def resolve_connection(
    conn: asyncpg.Connection[asyncpg.Record],
) -> ListmonkConnection | None:
    """Connexion à utiliser pour un envoi, ou None si aucune n'est réglée ou si le token
    n'est plus déchiffrable (HMAC_KEY changée) — dans ce cas, journalisé : l'admin doit
    ressaisir le token."""
    row = await repo.db_get(conn)
    if row is None:
        return None
    try:
        token = server_secret_box.unseal(row.token_encrypted, purpose=_TOKEN_PURPOSE)
    except (InvalidTag, ValueError):
        logger.error("listmonk_token_undecryptable")
        return None
    return ListmonkConnection(url=row.url, api_user=row.api_user, token=SecretStr(token))


def _token_required(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": "token_required", "message": message},
    )


async def _reusable_stored_token(
    conn: asyncpg.Connection[asyncpg.Record], url: str
) -> tuple[bytes, SecretStr]:
    """Token enregistré, réutilisable seulement vers la MÊME URL.

    RÈGLE DE SÉCURITÉ : sans cette condition, un admin pourrait pointer la connexion (ou
    un simple test) vers un hôte qu'il contrôle et y recevoir le token en clair dans
    l'en-tête Authorization — le token, censé ne jamais se relire, se relirait ainsi.
    Changer d'URL impose donc de ressaisir le token. Un token devenu illisible (clé
    serveur changée) n'est pas réutilisable non plus : l'enregistrer tel quel donnerait
    une connexion « réussie » qui n'enverrait aucun mail.
    """
    row = await repo.db_get(conn)
    if row is None:
        raise _token_required("A token is required")
    if row.url != url:
        raise _token_required("A token is required when the URL changes")
    try:
        token = server_secret_box.unseal(row.token_encrypted, purpose=_TOKEN_PURPOSE)
    except (InvalidTag, ValueError) as exc:
        raise _token_required("The saved token can no longer be decrypted") from exc
    return row.token_encrypted, SecretStr(token)


async def get_connection_view(
    conn: asyncpg.Connection[asyncpg.Record],
) -> ListmonkConnectionView | None:
    row = await repo.db_get(conn)
    if row is None:
        return None
    try:
        server_secret_box.unseal(row.token_encrypted, purpose=_TOKEN_PURPOSE)
        readable = True
    except (InvalidTag, ValueError):
        readable = False
    return ListmonkConnectionView(
        url=row.url, api_user=row.api_user, token_readable=readable, updated_at=row.updated_at
    )


async def save_connection(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    url: str,
    api_user: str,
    token: SecretStr | None,
    actor_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Enregistre la connexion. `token=None` garde le token déjà stocké (l'IHM ne le
    connaît pas et ne peut donc pas le renvoyer), à condition que l'URL ne change pas
    (voir `_reusable_stored_token`)."""
    async with conn.transaction():
        if token is None:
            token_encrypted, _ = await _reusable_stored_token(conn, url)
        else:
            token_encrypted = server_secret_box.seal(
                token.get_secret_value(), purpose=_TOKEN_PURPOSE
            )
        await repo.db_upsert(
            conn,
            url=url,
            api_user=api_user,
            token_encrypted=token_encrypted,
            updated_by_user_id=actor_user_id,
        )
        await audit_log_insert(
            conn,
            "listmonk_connection.updated",
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            # Jamais le token, même chiffré : seulement le fait qu'il a changé.
            metadata={"url": url, "api_user": api_user, "token_changed": token is not None},
        )


async def resolve_test_connection(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    url: str,
    api_user: str,
    token: SecretStr | None,
) -> ConnectionTestResult:
    """Teste des valeurs saisies avant enregistrement ; sans token, celui en base sert,
    vers la même URL seulement (voir `_reusable_stored_token`)."""
    if token is None:
        _, token = await _reusable_stored_token(conn, url)
    return await check_credentials(ListmonkConnection(url=url, api_user=api_user, token=token))


async def check_credentials(connection: ListmonkConnection) -> ConnectionTestResult:
    """Appelle `GET /api/health`, route authentifiée de Listmonk qui n'exige aucune
    permission : elle valide l'URL et les identifiants, PAS les droits `tx:send` /
    `subscribers:manage` requis à l'envoi. Le corps de la réponse n'est pas renvoyé à
    l'appelant (l'URL est saisie par l'admin : on ne fait pas de ce test un lecteur
    de pages arbitraires)."""
    try:
        async with httpx.AsyncClient(timeout=_TEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{connection.url}/api/health",
                headers={"Authorization": auth_header(connection)},
            )
    except httpx.HTTPError as exc:
        logger.info("listmonk_connection_test_unreachable", error=type(exc).__name__)
        return ConnectionTestResult(ok=False, http_status=None)
    return ConnectionTestResult(ok=response.status_code == 200, http_status=response.status_code)


async def import_legacy_env_connection(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    """Reprise UNIQUE de HARPOCRATE_LISTMONK_URL/USER/TOKEN au boot, si aucune connexion
    n'est en base. Jamais d'écrasement : la ligne posée depuis l'IHM fait foi. Pas de
    témoin nécessaire : l'IHM ne supprime pas la connexion, donc une ligne présente
    bloque définitivement la reprise."""
    if not (settings.listmonk_url and settings.listmonk_user and settings.listmonk_token):
        return
    try:
        url = validate_listmonk_url(settings.listmonk_url)
    except InvalidListmonkUrlError as exc:
        # URL legacy invalide (ex. identifiants embarqués) : à ressaisir dans l'IHM.
        logger.warning("listmonk_legacy_connection_rejected", reason=str(exc))
        return
    inserted = await repo.db_insert_if_absent(
        conn,
        url=url,
        api_user=settings.listmonk_user,
        token_encrypted=server_secret_box.seal(settings.listmonk_token, purpose=_TOKEN_PURPOSE),
    )
    logger.info("listmonk_legacy_connection_import", inserted=inserted)
