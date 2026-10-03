"""Migration 033 — tables du flux « Se connecter avec Harpocrate ».

Vérifie sur une vraie base (``HARPOCRATE_DB_DSN_TEST``) :
- ``connect_clients`` : colonnes, unicité et format du ``client_id``, URLs de
  retour non vides ;
- ``connect_requests`` : colonnes, statuts autorisés, cohérence imposée par la
  base entre le statut et le scellé (un scellé remis ne doit plus exister) ;
- ``api_keys.connect_client_id`` : colonne nullable (les clés existantes
  restent valides).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

_CLIENT_COLUMNS = [
    "id",
    "client_id",
    "name",
    "description",
    "redirect_uris",
    "active",
    "created_by_user_id",
    "created_at",
    "updated_at",
]

_REQUEST_COLUMNS = [
    "id",
    "request_ref_hash",
    "client_pk",
    "redirect_uri",
    "state",
    "code_challenge",
    "requested_permissions",
    "requested_ttl_days",
    "app_public_jwk",
    "status",
    "user_id",
    "wallet_id",
    "api_key_id",
    "sealed_jwe",
    "code_hash",
    "code_expires_at",
    "expires_at",
    "created_at",
]

_VALID_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
_JWK = '{"kty": "EC", "crv": "P-256", "x": "x", "y": "y"}'


async def _columns(conn: asyncpg.Connection[asyncpg.Record], table: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 "
        "ORDER BY ordinal_position",
        table,
    )
    return [r["column_name"] for r in rows]


@pytest.fixture()
async def tx_conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    """Connexion dans une transaction annulée en fin de test : rien ne persiste."""
    async with real_db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            yield conn
        finally:
            await tr.rollback()


async def _insert_client(
    conn: asyncpg.Connection[asyncpg.Record], client_id: str = "ragflow"
) -> object:
    return await conn.fetchval(
        "INSERT INTO connect_clients (client_id, name, redirect_uris) "
        "VALUES ($1, 'Ragflow', ARRAY['https://rag.example/cb']) RETURNING id",
        client_id,
    )


async def _insert_request(
    conn: asyncpg.Connection[asyncpg.Record],
    client_pk: object,
    *,
    ref: bytes = b"r" * 32,
    status: str = "pending",
    sealed_jwe: str | None = None,
    code_hash: bytes | None = None,
    code_expires: bool = False,
) -> None:
    await conn.execute(
        """
        INSERT INTO connect_requests
            (request_ref_hash, client_pk, redirect_uri, state, code_challenge,
             requested_permissions, app_public_jwk, status, sealed_jwe,
             code_hash, code_expires_at, expires_at)
        VALUES ($1, $2, 'https://rag.example/cb', 'st', $3, 1, $4::jsonb, $5, $6,
                $7, CASE WHEN $8 THEN NOW() + INTERVAL '60 seconds' END,
                NOW() + INTERVAL '15 minutes')
        """,
        ref,
        client_pk,
        _VALID_CHALLENGE,
        _JWK,
        status,
        sealed_jwe,
        code_hash,
        code_expires,
    )


async def test_connect_clients_columns(tx_conn: asyncpg.Connection[asyncpg.Record]) -> None:
    names = await _columns(tx_conn, "connect_clients")
    assert names == _CLIENT_COLUMNS


async def test_connect_requests_columns(tx_conn: asyncpg.Connection[asyncpg.Record]) -> None:
    names = await _columns(tx_conn, "connect_requests")
    assert names == _REQUEST_COLUMNS


async def test_api_keys_connect_client_id_is_nullable(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    nullable = await tx_conn.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'api_keys' "
        "AND column_name = 'connect_client_id'"
    )
    assert nullable == "YES"


async def test_connect_client_id_is_unique(tx_conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await _insert_client(tx_conn, "docflow")
    with pytest.raises(asyncpg.UniqueViolationError):
        await _insert_client(tx_conn, "docflow")


@pytest.mark.parametrize("bad_id", ["Ragflow", "ab", "-rag", "rag flow", "rag/flow", "x" * 65])
async def test_connect_client_id_format_is_enforced(
    tx_conn: asyncpg.Connection[asyncpg.Record], bad_id: str
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_client(tx_conn, bad_id)


async def test_connect_client_requires_at_least_one_redirect_uri(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await tx_conn.execute(
            "INSERT INTO connect_clients (client_id, name, redirect_uris) "
            "VALUES ('portal', 'Portail', ARRAY[]::TEXT[])"
        )


async def test_connect_request_status_is_constrained(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    client_pk = await _insert_client(tx_conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_request(tx_conn, client_pk, status="authorized")


async def test_sealed_request_requires_jwe_and_code(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    client_pk = await _insert_client(tx_conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_request(tx_conn, client_pk, status="sealed")


async def test_delivered_request_must_not_keep_the_sealed_jwe(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Invariant du cadrage : après remise, le scellé ne doit plus exister."""
    client_pk = await _insert_client(tx_conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_request(
            tx_conn,
            client_pk,
            status="delivered",
            sealed_jwe="eyJhbGciOi...",
            code_hash=b"c" * 32,
            code_expires=True,
        )


async def test_request_reference_is_unique(tx_conn: asyncpg.Connection[asyncpg.Record]) -> None:
    client_pk = await _insert_client(tx_conn)
    await _insert_request(tx_conn, client_pk, ref=b"same" * 8)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _insert_request(tx_conn, client_pk, ref=b"same" * 8)


async def test_code_challenge_format_is_enforced(
    tx_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    client_pk = await _insert_client(tx_conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await tx_conn.execute(
            """
            INSERT INTO connect_requests
                (request_ref_hash, client_pk, redirect_uri, state, code_challenge,
                 requested_permissions, app_public_jwk, expires_at)
            VALUES ($1, $2, 'https://rag.example/cb', 'st', 'plain-not-s256', 1,
                    $3::jsonb, NOW() + INTERVAL '15 minutes')
            """,
            b"z" * 32,
            client_pk,
            _JWK,
        )
