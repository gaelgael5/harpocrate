"""Routes /v1/connect/* (feature 2) — sur une vraie base, dans une transaction annulée.

Le pool de l'application est remplacé par un pool qui rend toujours la même connexion,
ouverte dans une transaction : les transactions du service deviennent des points de
sauvegarde, et rien ne survit au test.
"""

from __future__ import annotations

import base64
import datetime
from collections.abc import AsyncIterator, Generator
from typing import Any

import asyncpg
import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.log_redaction import loggable_path
from tests._connect_helpers import REDIRECT_URI, insert_client, make_jwk, par_body
from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_SUB = "connect-route-user"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)
    monkeypatch.setattr(_sec, "rate_limit_enabled", False, raising=False)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(backup)


@pytest.fixture()
async def conn(
    real_db_pool: asyncpg.Pool[asyncpg.Record], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    async with real_db_pool.acquire() as c:
        tr = c.transaction()
        await tr.start()

        class _Ctx:
            async def __aenter__(self) -> asyncpg.Connection[asyncpg.Record]:
                return c

            async def __aexit__(self, *_a: Any) -> None:
                return None

        class _Pool:
            def acquire(self) -> _Ctx:
                return _Ctx()

        async def _get_pool() -> _Pool:
            return _Pool()

        import app.api.v1.connect as connect_module

        monkeypatch.setattr(connect_module, "get_pool", _get_pool)
        try:
            yield c
        finally:
            await tr.rollback()


@pytest.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _local_admin_token() -> str:
    from app.core.config import settings

    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    payload = {
        "sub": "admin",
        "email": "admin@test",
        "iat": now,
        "exp": now + 3600,
        "iss": "harpocrate-local",
        "aud": settings.keycloak_client_id,
    }
    return pyjwt.encode(payload, base64.b64decode(settings.hmac_key), algorithm="HS256")


async def _insert_user_with_sub(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await conn.execute(
        """
        INSERT INTO users (keycloak_sub, email, rsa_public_key, salt_passphrase, salt_recovery,
                           encrypted_rsa_private_key, encrypted_sym_key_by_pass,
                           encrypted_sym_key_by_recovery, kdf_memory_kb, kdf_iterations,
                           kdf_parallelism, rsa_key_size)
        VALUES ($1, 'alice@example.com', '\\x00', '\\x00', '\\x00', '\\x00', '\\x00', '\\x00',
                65536, 3, 4, 2048)
        """,
        _SUB,
    )


async def _par(client: AsyncClient, **overrides: Any) -> Any:
    body = par_body().model_dump(mode="json", exclude_none=True)
    body.update(overrides)
    return await client.post("/v1/connect/par", json=body)


# ─── POST /v1/connect/par ─────────────────────────────────────────────────────


async def test_par_returns_request_uri_and_ttl(conn: Any, client: AsyncClient) -> None:
    await insert_client(conn)
    r = await _par(client)
    assert r.status_code == 201
    assert r.json()["expires_in"] == 900
    assert r.json()["request_uri"].startswith("urn:ietf:params:oauth:request_uri:")


async def test_par_refuses_undeclared_redirect_uri_without_redirecting(
    conn: Any, client: AsyncClient
) -> None:
    await insert_client(conn)
    r = await _par(client, redirect_uri=REDIRECT_URI + "/")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_redirect_uri"
    assert "location" not in r.headers


@pytest.mark.parametrize(
    "overrides",
    [
        {"code_challenge_method": "plain"},
        {"code_challenge": None},
        {"permissions": 64},
        {"permissions": 0},
        {"unexpected": "x"},
    ],
)
async def test_par_rejects_malformed_request(
    conn: Any, client: AsyncClient, overrides: dict[str, Any]
) -> None:
    await insert_client(conn)
    r = await _par(client, **overrides)
    assert r.status_code == 422


async def test_par_rejects_a_private_key_sent_by_mistake(conn: Any, client: AsyncClient) -> None:
    await insert_client(conn)
    _, jwk = make_jwk()
    jwk["d"] = "A" * 43
    r = await _par(client, app_public_jwk=jwk)
    assert r.status_code == 422


async def test_par_rejects_a_point_off_the_curve(conn: Any, client: AsyncClient) -> None:
    await insert_client(conn)
    _, jwk = make_jwk()
    jwk["y"] = jwk["x"]
    r = await _par(client, app_public_jwk=jwk)
    assert r.status_code == 422


# ─── GET /v1/connect/requests/{request_uri} ──────────────────────────────────


async def _deposit(conn: Any, client: AsyncClient) -> str:
    await insert_client(conn)
    r = await _par(client)
    return str(r.json()["request_uri"])


async def test_get_request_shows_declared_name_to_keycloak_user(
    conn: Any, client: AsyncClient
) -> None:
    uri = await _deposit(conn, client)
    await _insert_user_with_sub(conn)
    r = await client.get(
        f"/v1/connect/requests/{uri}",
        params={"client_id": "ragflow"},
        headers=_bearer(make_jwt_token(sub=_SUB)),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["client"]["name"] == "Ragflow (déclaré)"
    assert data["redirect_uri"] == REDIRECT_URI
    assert data["requested_permissions"] == 3
    assert data["app_public_jwk"]["crv"] == "P-256"


async def test_get_request_refuses_local_admin(conn: Any, client: AsyncClient) -> None:
    uri = await _deposit(conn, client)
    r = await client.get(
        f"/v1/connect/requests/{uri}",
        params={"client_id": "ragflow"},
        headers=_bearer(_local_admin_token()),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "local_admin_not_allowed"


async def test_get_request_requires_authentication(conn: Any, client: AsyncClient) -> None:
    uri = await _deposit(conn, client)
    r = await client.get(f"/v1/connect/requests/{uri}", params={"client_id": "ragflow"})
    assert r.status_code == 401


async def test_get_request_sends_unbootstrapped_user_to_first_login(
    conn: Any, client: AsyncClient
) -> None:
    uri = await _deposit(conn, client)
    r = await client.get(
        f"/v1/connect/requests/{uri}",
        params={"client_id": "ragflow"},
        headers=_bearer(make_jwt_token(sub="never-bootstrapped")),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "first_login"


async def test_get_request_rejects_malformed_reference(conn: Any, client: AsyncClient) -> None:
    r = await client.get(
        "/v1/connect/requests/not-a-reference",
        params={"client_id": "ragflow"},
        headers=_bearer(make_jwt_token(sub=_SUB)),
    )
    assert r.status_code == 422


# ─── Journaux ─────────────────────────────────────────────────────────────────


def test_loggable_path_redacts_connect_request_reference() -> None:
    ref = "urn:ietf:params:oauth:request_uri:" + "Z" * 43
    assert loggable_path(f"/v1/connect/requests/{ref}") == "/v1/connect/requests/[redacted]"
    assert (
        loggable_path(f"/v1/connect/requests/{ref}/deny") == "/v1/connect/requests/[redacted]/deny"
    )
    assert loggable_path("/v1/wallets/abc") == "/v1/wallets/abc"


# ─── Refus, création, scellé, échange (features 3 à 5) ───────────────────────


async def _opened(conn: Any, client: AsyncClient) -> tuple[str, Any]:
    """Demande déposée puis ouverte par l'utilisateur ; renvoie (request_uri, wallet_id)."""
    from tests._connect_helpers import insert_wallet

    uri = await _deposit(conn, client)
    await _insert_user_with_sub(conn)
    user_id = await conn.fetchval("SELECT id FROM users WHERE keycloak_sub = $1", _SUB)
    wallet = await insert_wallet(conn, user_id)
    return uri, wallet


def _key_json(wallet: Any, **extra: Any) -> dict[str, Any]:
    from tests._connect_helpers import api_key_body

    body = api_key_body(wallet).model_dump(mode="json")
    body.update(extra)
    return body


async def test_deny_route_returns_access_denied_redirect(conn: Any, client: AsyncClient) -> None:
    uri, _ = await _opened(conn, client)
    r = await client.post(
        f"/v1/connect/requests/{uri}/deny",
        params={"client_id": "ragflow"},
        headers=_bearer(make_jwt_token(sub=_SUB)),
    )
    assert r.status_code == 200
    assert r.json()["redirect_to"].startswith(REDIRECT_URI + "?error=access_denied&state=")


async def test_api_key_route_refuses_a_decryption_key(conn: Any, client: AsyncClient) -> None:
    uri, wallet = await _opened(conn, client)
    r = await client.post(
        f"/v1/connect/requests/{uri}/api-key",
        params={"client_id": "ragflow"},
        json=_key_json(wallet, decryption_key="B" * 43),
        headers=_bearer(make_jwt_token(sub=_SUB)),
    )
    assert r.status_code == 422
    assert await conn.fetchval("SELECT count(*) FROM api_keys") == 0


async def test_api_key_route_refuses_local_admin(conn: Any, client: AsyncClient) -> None:
    uri, wallet = await _opened(conn, client)
    r = await client.post(
        f"/v1/connect/requests/{uri}/api-key",
        params={"client_id": "ragflow"},
        json=_key_json(wallet),
        headers=_bearer(_local_admin_token()),
    )
    assert r.status_code == 403


async def test_full_flow_over_http(conn: Any, client: AsyncClient) -> None:
    from urllib.parse import parse_qs, urlsplit

    from tests._connect_helpers import fake_jwe, insert_wallet, par_body_with_verifier

    await insert_client(conn)
    body, verifier = par_body_with_verifier()
    par = await client.post("/v1/connect/par", json=body.model_dump(mode="json", exclude_none=True))
    uri = par.json()["request_uri"]
    await _insert_user_with_sub(conn)
    user_id = await conn.fetchval("SELECT id FROM users WHERE keycloak_sub = $1", _SUB)
    wallet = await insert_wallet(conn, user_id)
    auth = _bearer(make_jwt_token(sub=_SUB))
    base = f"/v1/connect/requests/{uri}"
    q = {"client_id": "ragflow"}

    assert (await client.get(base, params=q, headers=auth)).status_code == 200
    created = await client.post(f"{base}/api-key", params=q, json=_key_json(wallet), headers=auth)
    assert created.status_code == 201
    jwe = fake_jwe()
    sealed = await client.post(f"{base}/sealed", params=q, json={"jwe": jwe}, headers=auth)
    assert sealed.status_code == 200
    code = parse_qs(urlsplit(sealed.json()["redirect_to"]).query)["code"][0]

    token = {
        "client_id": "ragflow",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }
    exchanged = await client.post("/v1/connect/token", json=token)
    assert exchanged.status_code == 200
    assert exchanged.json() == {
        "jwe": jwe,
        "api_key_id": created.json()["api_key_id"],
        "wallet_id": str(wallet),
    }
    replay = await client.post("/v1/connect/token", json=token)
    assert replay.status_code == 400 and replay.json()["detail"]["error"] == "invalid_grant"


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "RSA-OAEP", "enc": "A256GCM"},
        {"alg": "ECDH-ES", "enc": "A128GCM"},
        {"alg": "ECDH-ES", "enc": "A256GCM", "epk": {"kty": "OKP", "crv": "X25519"}},
    ],
)
async def test_sealed_route_rejects_unexpected_jwe_algorithms(
    conn: Any, client: AsyncClient, header: dict[str, Any]
) -> None:
    import json

    from tests._connect_helpers import b64url

    uri, _ = await _opened(conn, client)
    jwe = f"{b64url(json.dumps(header).encode())}..aaaa.bbbb.cccc"
    r = await client.post(
        f"/v1/connect/requests/{uri}/sealed",
        params={"client_id": "ragflow"},
        json={"jwe": jwe},
        headers=_bearer(make_jwt_token(sub=_SUB)),
    )
    assert r.status_code == 422
