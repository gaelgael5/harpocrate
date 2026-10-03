"""Refus, création de clé sans dkey et scellement (features 3 et 4) — sur une vraie base.

Invariants du cadrage couverts : 3 (le token signé par le serveur ne porte pas la dkey),
4 (permissions ⊆ demandées ∩ droits de l'utilisateur), 5 (`state` inchangé), 6 (refus →
`access_denied`, aucune clé).
"""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import asyncpg
import pytest
from fastapi import HTTPException

from app.core.api_key_token import DKEY_PLACEHOLDER, parse_token
from app.services import connect_keys, connect_requests
from tests._connect_helpers import (
    NOW,
    REDIRECT_URI,
    api_key_body,
    fake_jwe,
    insert_client,
    insert_user,
    insert_wallet,
    par_body,
)


@pytest.fixture()
async def conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    async with real_db_pool.acquire() as c:
        tr = c.transaction()
        await tr.start()
        try:
            yield c
        finally:
            await tr.rollback()


async def _error_of(coro: Any) -> tuple[int, str]:
    with pytest.raises(HTTPException) as exc:
        await coro
    return exc.value.status_code, exc.value.detail["error"]  # type: ignore[index]


async def _setup(
    conn: asyncpg.Connection[asyncpg.Record], **par: Any
) -> tuple[str, UUID, UUID, str]:
    """(request_uri, user_id, wallet_id, state) — demande ouverte par son utilisateur."""
    await insert_client(conn)
    user = await insert_user(conn)
    wallet = await insert_wallet(conn, user)
    body = par_body(**par)
    uri = await connect_requests.create_request(conn, body=body, now=NOW, actor_ip=None)
    await connect_requests.open_request(
        conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW
    )
    return uri, user, wallet, body.state


def _create(conn: Any, uri: str, user: UUID, body: Any, now: datetime.datetime = NOW) -> Any:
    return connect_keys.create_connect_api_key(
        conn,
        request_uri=uri,
        client_id="ragflow",
        body=body,
        user_id=user,
        now=now,
        actor_ip=None,
    )


def _seal(conn: Any, uri: str, user: UUID) -> Any:
    return connect_keys.seal_request(
        conn,
        request_uri=uri,
        client_id="ragflow",
        jwe=fake_jwe(),
        user_id=user,
        now=NOW,
        actor_ip=None,
    )


# ─── Refus (feature 3) ────────────────────────────────────────────────────────


async def test_deny_redirects_with_access_denied_and_unchanged_state(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, _, state = await _setup(conn, state="état/€ & = ?")
    redirect = await connect_requests.deny_request(
        conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW, actor_ip=None
    )
    parts = urlsplit(redirect)
    assert redirect.startswith(REDIRECT_URI + "?")
    assert parse_qs(parts.query) == {"error": ["access_denied"], "state": [state]}
    assert await conn.fetchval("SELECT status FROM connect_requests") == "denied"
    assert await conn.fetchval("SELECT count(*) FROM api_keys") == 0
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action = 'connect_request.denied'"
        )
        == 1
    )


async def test_deny_twice_is_refused(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    uri, user, _, _ = await _setup(conn)
    kwargs: dict[str, Any] = {
        "request_uri": uri,
        "client_id": "ragflow",
        "user_id": user,
        "now": NOW,
        "actor_ip": None,
    }
    await connect_requests.deny_request(conn, **kwargs)
    assert await _error_of(connect_requests.deny_request(conn, **kwargs)) == (
        409,
        "request_not_pending",
    )


def test_redirect_with_keeps_the_declared_query() -> None:
    url = connect_requests.redirect_with("https://app.example/cb?tenant=a", {"code": "x"})
    assert parse_qs(urlsplit(url).query) == {"tenant": ["a"], "code": ["x"]}


# ─── Création de la clé (feature 4) ───────────────────────────────────────────


async def test_create_key_signs_token_without_dkey_and_links_application(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, wallet, _ = await _setup(conn, permissions=0x03, ttl_days=90)
    body = api_key_body(wallet, permissions=0x01, ttl_days=30)

    result = await _create(conn, uri, user, body)

    parsed = parse_token(result.token)
    assert parsed.dkey_b64 == DKEY_PLACEHOLDER
    assert parsed.auth_secret_b64 == body.auth_secret
    assert parsed.perms == 0x01
    assert parsed.exp == int((NOW + datetime.timedelta(days=30)).timestamp())
    key = await conn.fetchrow(
        "SELECT k.wallet_id, k.permissions, c.client_id, k.name FROM api_keys k "
        "JOIN connect_clients c ON c.id = k.connect_client_id WHERE k.id = $1",
        result.api_key_id,
    )
    assert key is not None
    assert (key["wallet_id"], key["permissions"], key["client_id"]) == (wallet, 1, "ragflow")
    assert key["name"] == "Ragflow (déclaré)"
    req = await conn.fetchrow("SELECT wallet_id, api_key_id, status FROM connect_requests")
    assert req is not None and (req["wallet_id"], req["api_key_id"]) == (wallet, result.api_key_id)
    assert req["status"] == "pending"
    audit = await conn.fetchval(
        "SELECT metadata->>'connect_client_id' FROM audit_log WHERE action = 'api_key.created'"
    )
    assert audit == "ragflow"


async def test_create_key_refuses_permissions_beyond_the_request(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, wallet, _ = await _setup(conn, permissions=0x01)
    assert await _error_of(_create(conn, uri, user, api_key_body(wallet, permissions=0x03))) == (
        400,
        "permissions_exceed_request",
    )
    assert await conn.fetchval("SELECT count(*) FROM api_keys") == 0


async def test_create_key_refuses_permissions_beyond_user_rights(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    user = await insert_user(conn)
    wallet = await insert_wallet(conn, user, permissions=0x20 | 0x01)  # share + read
    uri = await connect_requests.create_request(
        conn, body=par_body(permissions=0x03), now=NOW, actor_ip=None
    )
    assert await _error_of(_create(conn, uri, user, api_key_body(wallet, permissions=0x02))) == (
        400,
        "permissions_exceed_request",
    )


async def test_create_key_requires_share_on_the_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    user = await insert_user(conn)
    wallet = await insert_wallet(conn, user, permissions=0x01)
    uri = await connect_requests.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    assert await _error_of(_create(conn, uri, user, api_key_body(wallet))) == (
        403,
        "missing_share_permission",
    )


async def test_create_key_refuses_a_deleted_wallet(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, wallet, _ = await _setup(conn)
    await conn.execute("UPDATE wallets SET deleted_at = NOW() WHERE id = $1", wallet)
    assert await _error_of(_create(conn, uri, user, api_key_body(wallet))) == (
        404,
        "wallet_not_found",
    )


async def test_create_key_refuses_a_wallet_of_someone_else(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, _, _ = await _setup(conn)
    other_wallet = await insert_wallet(conn, await insert_user(conn))
    assert await _error_of(_create(conn, uri, user, api_key_body(other_wallet))) == (
        404,
        "wallet_not_found",
    )


@pytest.mark.parametrize("ttl_days", [None, 91])
async def test_create_key_refuses_lifetime_beyond_the_request(
    conn: asyncpg.Connection[asyncpg.Record], ttl_days: int | None
) -> None:
    uri, user, wallet, _ = await _setup(conn, ttl_days=90)
    assert await _error_of(_create(conn, uri, user, api_key_body(wallet, ttl_days=ttl_days))) == (
        400,
        "ttl_exceeds_request",
    )


async def test_create_key_without_requested_lifetime_accepts_none(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, wallet, _ = await _setup(conn, ttl_days=None)
    result = await _create(conn, uri, user, api_key_body(wallet, ttl_days=None))
    assert parse_token(result.token).exp == 0


async def test_create_key_only_once_per_request(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    uri, user, wallet, _ = await _setup(conn)
    await _create(conn, uri, user, api_key_body(wallet))
    assert await _error_of(_create(conn, uri, user, api_key_body(wallet))) == (
        409,
        "api_key_already_created",
    )


# ─── Scellement et code (feature 4) ───────────────────────────────────────────


async def test_seal_requires_the_key_first(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    uri, user, _, _ = await _setup(conn)
    assert await _error_of(_seal(conn, uri, user)) == (409, "api_key_missing")


async def test_seal_issues_a_hashed_single_use_code(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    uri, user, wallet, state = await _setup(conn)
    await _create(conn, uri, user, api_key_body(wallet))

    redirect = await _seal(conn, uri, user)

    query = parse_qs(urlsplit(redirect).query)
    assert redirect.startswith(REDIRECT_URI + "?")
    assert query["state"] == [state]
    code = query["code"][0]
    row = await conn.fetchrow(
        "SELECT status, code_hash, code_expires_at, sealed_jwe FROM connect_requests"
    )
    assert row is not None
    assert row["status"] == "sealed"
    assert bytes(row["code_hash"]) == hashlib.sha256(code.encode()).digest()
    assert row["code_expires_at"] == NOW + datetime.timedelta(seconds=60)
    assert code not in str(dict(row))
    # La demande est close pour le navigateur : ni nouveau scellé, ni refus.
    assert await _error_of(_seal(conn, uri, user)) == (409, "request_not_pending")


async def test_api_key_listing_names_the_application(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    from app.db.repositories import api_keys as api_keys_repo

    uri, user, wallet, _ = await _setup(conn)
    created = await _create(conn, uri, user, api_key_body(wallet))
    items = await api_keys_repo.list_api_keys_for_wallet(conn, wallet_id=wallet)
    by_id = {i.id: i for i in items}
    linked = by_id[created.api_key_id].connect_client
    assert linked is not None
    assert (linked.client_id, linked.name) == ("ragflow", "Ragflow (déclaré)")
