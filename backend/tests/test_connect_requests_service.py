"""Service des demandes de connexion (feature 2) — sur une vraie base.

Couvre l'invariant 1 du cadrage (URL de retour exacte, refus AVANT toute redirection),
l'expiration (D9) et l'appropriation de la demande par le premier utilisateur qui l'ouvre.
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator

import asyncpg
import pytest
from fastapi import HTTPException

from app.db.repositories import connect_clients as clients_repo
from app.db.repositories import connect_requests as repo
from app.services import connect_requests as svc
from tests._connect_helpers import (
    NOW,
    REDIRECT_URI,
    insert_client,
    insert_user,
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


async def _error_of(coro: object) -> tuple[int, str]:
    with pytest.raises(HTTPException) as exc:
        await coro  # type: ignore[misc]
    return exc.value.status_code, exc.value.detail["error"]  # type: ignore[index]


# ─── Dépôt (PAR) ──────────────────────────────────────────────────────────────


async def test_create_request_stores_only_the_hash_of_the_reference(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    body = par_body()
    request_uri = await svc.create_request(conn, body=body, now=NOW, actor_ip="10.0.0.1")

    assert request_uri.startswith("urn:ietf:params:oauth:request_uri:")
    row = await repo.db_get_by_ref_hash(conn, svc.ref_hash(request_uri))
    assert row is not None
    assert row.status == "pending"
    assert row.state == body.state
    assert row.expires_at == NOW + datetime.timedelta(minutes=15)
    assert row.app_public_jwk["x"] == body.app_public_jwk.x
    # La référence en clair n'est stockée dans aucune colonne texte de la demande.
    as_text = await conn.fetchval(
        "SELECT row_to_json(r)::text FROM connect_requests r WHERE redirect_uri = $1", REDIRECT_URI
    )
    assert request_uri.split(":")[-1] not in as_text


async def test_create_request_audits_reception(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await insert_client(conn)
    await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    count = await conn.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'connect_request.received' "
        "AND metadata->>'client_id' = 'ragflow'"
    )
    assert count == 1


async def test_create_request_refuses_unknown_client(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    assert await _error_of(
        svc.create_request(conn, body=par_body("inconnu"), now=NOW, actor_ip=None)
    ) == (400, "invalid_client")


async def test_create_request_refuses_disabled_client(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    client = await insert_client(conn)
    await clients_repo.db_update(
        conn,
        client.id,
        name=client.name,
        description=None,
        redirect_uris=client.redirect_uris,
        active=False,
    )
    assert await _error_of(svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)) == (
        400,
        "invalid_client",
    )


@pytest.mark.parametrize(
    "variant",
    [
        REDIRECT_URI + "/",
        REDIRECT_URI.upper(),
        REDIRECT_URI.replace("rag.example", "rag.example:443"),
        REDIRECT_URI + "?x=1",
        "https://evil.example/harpocrate/callback",
    ],
)
async def test_create_request_refuses_any_redirect_uri_variant(
    conn: asyncpg.Connection[asyncpg.Record], variant: str
) -> None:
    await insert_client(conn)
    assert await _error_of(
        svc.create_request(conn, body=par_body(redirect_uri=variant), now=NOW, actor_ip=None)
    ) == (400, "invalid_redirect_uri")
    assert await conn.fetchval("SELECT count(*) FROM connect_requests") == 0


# ─── Ouverture par l'utilisateur ──────────────────────────────────────────────


async def test_open_request_claims_it_for_the_first_user(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    user = await insert_user(conn)
    uri = await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)

    row = await svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW)

    assert row.user_id == user
    assert row.client_name == "Ragflow (déclaré)"
    stored = await repo.db_get_by_ref_hash(conn, svc.ref_hash(uri))
    assert stored is not None and stored.user_id == user
    # Rouvrir (rechargement de page) reste possible pour le même utilisateur.
    again = await svc.open_request(
        conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW
    )
    assert again.id == row.id


async def test_open_request_hides_it_from_another_user(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    owner, intruder = await insert_user(conn), await insert_user(conn)
    uri = await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    await svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=owner, now=NOW)

    assert await _error_of(
        svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=intruder, now=NOW)
    ) == (404, "request_not_found")


async def test_open_request_refuses_unknown_reference(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    user = await insert_user(conn)
    uri = "urn:ietf:params:oauth:request_uri:" + "A" * 43
    assert await _error_of(
        svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW)
    ) == (404, "request_not_found")


async def test_open_request_refuses_reference_of_another_client(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    await insert_client(conn, "docflow")
    user = await insert_user(conn)
    uri = await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    assert await _error_of(
        svc.open_request(conn, request_uri=uri, client_id="docflow", user_id=user, now=NOW)
    ) == (404, "request_not_found")


async def test_open_request_refuses_expired_request(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    user = await insert_user(conn)
    uri = await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    later = NOW + datetime.timedelta(minutes=15)
    assert await _error_of(
        svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=user, now=later)
    ) == (410, "request_expired")


async def test_open_request_refuses_when_client_disabled_after_deposit(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    client = await insert_client(conn)
    user = await insert_user(conn)
    uri = await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    await clients_repo.db_update(
        conn,
        client.id,
        name=client.name,
        description=None,
        redirect_uris=client.redirect_uris,
        active=False,
    )
    assert await _error_of(
        svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW)
    ) == (404, "request_not_found")


async def test_open_request_refuses_answered_request(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    await insert_client(conn)
    user = await insert_user(conn)
    uri = await svc.create_request(conn, body=par_body(), now=NOW, actor_ip=None)
    await conn.execute("UPDATE connect_requests SET status = 'denied'")
    assert await _error_of(
        svc.open_request(conn, request_uri=uri, client_id="ragflow", user_id=user, now=NOW)
    ) == (409, "request_not_pending")
