"""Échange du code et purge (feature 5) — sur une vraie base.

Invariants du cadrage couverts : 2 (code unique, TTL, PKCE ; rejeu journalisé en
anomalie), 3 (plus de scellé en base après remise), 7 (audit), et D13 (clé non livrée
révoquée par la purge, horloge injectée).
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import asyncpg
import pytest
from fastapi import HTTPException

from app.models.api.connect_flow import ConnectTokenRequest
from app.services import connect_exchange, connect_keys, connect_requests
from tests._connect_helpers import (
    NOW,
    REDIRECT_URI,
    api_key_body,
    fake_jwe,
    insert_client,
    insert_user,
    insert_wallet,
    make_pkce,
    par_body_with_verifier,
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


class Flow:
    """Une demande menée jusqu'au code, prête à être échangée."""

    def __init__(self, code: str, verifier: str, jwe: str, api_key_id: UUID, wallet: UUID) -> None:
        self.code, self.verifier, self.jwe = code, verifier, jwe
        self.api_key_id, self.wallet = api_key_id, wallet

    def token_request(self, **overrides: Any) -> ConnectTokenRequest:
        fields = {
            "client_id": "ragflow",
            "code": self.code,
            "code_verifier": self.verifier,
            "redirect_uri": REDIRECT_URI,
        }
        fields.update(overrides)
        return ConnectTokenRequest.model_validate(fields)


async def _flow(conn: asyncpg.Connection[asyncpg.Record], *, seal: bool = True) -> Flow:
    await insert_client(conn)
    user = await insert_user(conn)
    wallet = await insert_wallet(conn, user)
    body, verifier = par_body_with_verifier()
    uri = await connect_requests.create_request(conn, body=body, now=NOW, actor_ip=None)
    common: dict[str, Any] = {"request_uri": uri, "client_id": "ragflow", "user_id": user}
    key = await connect_keys.create_connect_api_key(
        conn, body=api_key_body(wallet), now=NOW, actor_ip=None, **common
    )
    jwe = fake_jwe()
    code = ""
    if seal:
        redirect = await connect_keys.seal_request(conn, jwe=jwe, now=NOW, actor_ip=None, **common)
        code = parse_qs(urlsplit(redirect).query)["code"][0]
    return Flow(code, verifier, jwe, key.api_key_id, wallet)


async def _exchange(conn: Any, req: ConnectTokenRequest, now: datetime.datetime = NOW) -> Any:
    return await connect_exchange.exchange_code(conn, body=req, now=now, actor_ip="10.1.1.1")


async def _refused(conn: Any, req: ConnectTokenRequest, now: datetime.datetime = NOW) -> str:
    with pytest.raises(HTTPException) as exc:
        await _exchange(conn, req, now)
    assert exc.value.status_code == 400
    return str(exc.value.detail["error"])  # type: ignore[index]


async def _audit_count(conn: Any, action: str) -> int:
    return int(await conn.fetchval("SELECT count(*) FROM audit_log WHERE action = $1", action))


# ─── Échange ──────────────────────────────────────────────────────────────────


async def test_exchange_delivers_the_seal_once_then_erases_it(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    flow = await _flow(conn)

    result = await _exchange(conn, flow.token_request())

    assert (result.jwe, result.api_key_id, result.wallet_id) == (
        flow.jwe,
        flow.api_key_id,
        flow.wallet,
    )
    row = await conn.fetchrow("SELECT status, sealed_jwe FROM connect_requests")
    assert row is not None and row["status"] == "delivered" and row["sealed_jwe"] is None
    assert await _audit_count(conn, "connect_code.exchanged") == 1


async def test_exchange_replay_is_refused_and_reported_as_anomaly(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    flow = await _flow(conn)
    await _exchange(conn, flow.token_request())

    assert await _refused(conn, flow.token_request()) == "invalid_grant"
    assert await _audit_count(conn, "connect_code.replayed") == 1
    anomalies = await conn.fetchval(
        "SELECT count(*) FROM system_anomaly_events WHERE anomaly_type = 'connect_code_replayed'"
    )
    assert anomalies == 1


async def test_exchange_refuses_an_expired_code(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    flow = await _flow(conn)
    later = NOW + datetime.timedelta(seconds=60)
    assert await _refused(conn, flow.token_request(), later) == "invalid_grant"
    assert await _audit_count(conn, "connect_code.expired") == 1
    assert await conn.fetchval("SELECT sealed_jwe FROM connect_requests") is not None


async def test_exchange_refuses_a_wrong_code_verifier(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    flow = await _flow(conn)
    other_verifier, _ = make_pkce()
    assert await _refused(conn, flow.token_request(code_verifier=other_verifier)) == "invalid_grant"
    assert await _audit_count(conn, "connect_code.pkce_failed") == 1
    # Le bon vérificateur fonctionne encore : un essai raté ne brûle pas le code.
    assert (await _exchange(conn, flow.token_request())).jwe == flow.jwe


@pytest.mark.parametrize(
    "overrides",
    [{"client_id": "docflow"}, {"redirect_uri": REDIRECT_URI + "/other"}],
)
async def test_exchange_refuses_another_client_or_redirect_uri(
    conn: asyncpg.Connection[asyncpg.Record], overrides: dict[str, str]
) -> None:
    flow = await _flow(conn)
    assert await _refused(conn, flow.token_request(**overrides)) == "invalid_grant"
    assert await _audit_count(conn, "connect_code.client_mismatch") == 1


async def test_exchange_refuses_an_unknown_code(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    flow = await _flow(conn)
    unknown, _ = make_pkce()
    assert await _refused(conn, flow.token_request(code=unknown)) == "invalid_grant"


# ─── Purge (D13) ──────────────────────────────────────────────────────────────


async def _revoked(conn: Any, api_key_id: UUID) -> bool:
    return bool(
        await conn.fetchval("SELECT revoked_at IS NOT NULL FROM api_keys WHERE id = $1", api_key_id)
    )


@pytest.mark.parametrize("seal", [True, False])
async def test_purge_revokes_undelivered_key_and_deletes_request(
    conn: asyncpg.Connection[asyncpg.Record], seal: bool
) -> None:
    flow = await _flow(conn, seal=seal)
    after = NOW + datetime.timedelta(minutes=15)

    deleted = await connect_exchange.purge_expired_requests(conn, now=after)

    assert deleted == 1
    assert await _revoked(conn, flow.api_key_id)
    assert await conn.fetchval("SELECT count(*) FROM connect_requests") == 0
    reason = await conn.fetchval(
        "SELECT metadata->>'reason' FROM audit_log WHERE action = 'api_key.revoked'"
    )
    assert reason == "connect_not_delivered"


async def test_purge_keeps_delivered_key_active(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    flow = await _flow(conn)
    await _exchange(conn, flow.token_request())

    await connect_exchange.purge_expired_requests(conn, now=NOW + datetime.timedelta(minutes=15))

    assert not await _revoked(conn, flow.api_key_id)
    assert await conn.fetchval("SELECT count(*) FROM connect_requests") == 0


async def test_purge_leaves_pending_requests_alone(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    flow = await _flow(conn, seal=False)
    deleted = await connect_exchange.purge_expired_requests(
        conn, now=NOW + datetime.timedelta(minutes=14)
    )
    assert deleted == 0
    assert not await _revoked(conn, flow.api_key_id)


async def test_full_flow_keeps_no_trace_of_the_seal_or_code(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    flow = await _flow(conn)
    await _exchange(conn, flow.token_request())
    dump = await conn.fetchval(
        "SELECT string_agg(row_to_json(r)::text, '') FROM connect_requests r"
    )
    assert dump  # la demande livrée existe encore (empreinte du code gardée pour le rejeu)
    audit = await conn.fetchval(
        "SELECT string_agg(coalesce(metadata::text, ''), '') FROM audit_log"
    )
    for trace in (flow.jwe, flow.code):
        assert trace not in (dump or "")
        assert trace not in (audit or "")
