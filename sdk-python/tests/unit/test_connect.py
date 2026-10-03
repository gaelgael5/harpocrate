"""Assistant « Se connecter avec Harpocrate » (feature 6) — sans serveur.

Le serveur est simulé par un transport httpx ; le navigateur, par un scellement joserfc
fait avec la clé PUBLIQUE de la demande, exactement comme le fait l'écran de
consentement (JWE ECDH-ES / A256GCM).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from typing import Any

import httpx
import pytest
from joserfc import jwe
from joserfc.jwk import ECKey

from harpocrate import connect
from harpocrate.exceptions import ConnectError
from harpocrate.token import parse_token

BASE = "https://vault.example"
REDIRECT = "https://rag.example/cb"
API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
WALLET_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _signed_token() -> str:
    """Token tel que le serveur le signe : segment dkey de substitution."""
    id_b32 = base64.b32encode(API_KEY_ID.bytes).decode().lower().rstrip("=")
    return f"hrpv_1_{id_b32}_0_01_{_b64url(os.urandom(32))}_{'A' * 43}_{_b64url(os.urandom(16))}"


class FakeServer:
    """Enregistre les requêtes ; répond au PAR puis à l'échange avec un scellé."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.dkey = _b64url(os.urandom(32))
        self.token = _signed_token()
        self.sealed: str | None = None
        self.par_status = 201

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        if request.url.path == "/v1/connect/par":
            if self.par_status != 201:
                return httpx.Response(self.par_status, json={"detail": {"error": "invalid_client"}})
            public = ECKey.import_key(body["app_public_jwk"])
            payload = json.dumps({"token": self.token, "dkey": self.dkey}).encode()
            self.sealed = jwe.encrypt_compact({"alg": "ECDH-ES", "enc": "A256GCM"}, payload, public)
            return httpx.Response(
                201, json={"request_uri": "urn:ietf:params:oauth:request_uri:" + "r" * 43}
            )
        return httpx.Response(
            200,
            json={"jwe": self.sealed, "api_key_id": str(API_KEY_ID), "wallet_id": str(WALLET_ID)},
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _start(server: FakeServer) -> tuple[str, connect.ConnectState]:
    return connect.start(BASE, "ragflow", REDIRECT, 0x01, 90, http_client=server.client())


def test_start_deposits_pkce_s256_and_public_key_only() -> None:
    server = FakeServer()
    url, pending = _start(server)

    path, body = server.requests[0]
    assert path == "/v1/connect/par"
    assert body["code_challenge_method"] == "S256"
    expected = _b64url(hashlib.sha256(pending.code_verifier.encode()).digest())
    assert body["code_challenge"] == expected
    assert "d" not in body["app_public_jwk"]
    assert pending.private_jwk["d"]
    assert body["state"] == pending.state
    assert url == (
        f"{BASE}/connect?client_id=ragflow&request_uri="
        "urn%3Aietf%3Aparams%3Aoauth%3Arequest_uri%3A" + "r" * 43
    )


def test_start_reports_the_server_error_code() -> None:
    server = FakeServer()
    server.par_status = 400
    with pytest.raises(ConnectError) as exc:
        _start(server)
    assert exc.value.error_code == "invalid_client"


def test_start_refuses_plain_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARPOCRATE_ALLOW_INSECURE", raising=False)
    with pytest.raises(ValueError):
        connect.start("http://vault.example", "ragflow", REDIRECT, 1)


def test_finish_unseals_and_reinserts_the_dkey() -> None:
    server = FakeServer()
    _, pending = _start(server)

    result = connect.finish(
        pending, code="c" * 43, state=pending.state, http_client=server.client()
    )

    parsed = parse_token(result.token)
    assert parsed.dkey_b64 == server.dkey
    assert (result.api_key_id, result.wallet_id) == (API_KEY_ID, WALLET_ID)
    path, body = server.requests[1]
    assert path == "/v1/connect/token"
    assert body == {
        "client_id": "ragflow",
        "code": "c" * 43,
        "code_verifier": pending.code_verifier,
        "redirect_uri": REDIRECT,
    }


def test_finish_refuses_a_foreign_state_without_calling_the_server() -> None:
    server = FakeServer()
    _, pending = _start(server)
    with pytest.raises(ConnectError) as exc:
        connect.finish(pending, code="c" * 43, state="other", http_client=server.client())
    assert exc.value.error_code == "state_mismatch"
    assert len(server.requests) == 1


def test_finish_refuses_a_seal_for_another_key() -> None:
    server = FakeServer()
    _, pending = _start(server)
    other = connect.ConnectState.from_dict(
        {**pending.to_dict(), "private_jwk": ECKey.generate_key("P-256").as_dict(private=True)}
    )
    with pytest.raises(ConnectError) as exc:
        connect.finish(other, code="c" * 43, state=pending.state, http_client=server.client())
    assert exc.value.error_code == "invalid_seal"


def test_state_survives_serialization_and_hides_secrets_in_repr() -> None:
    server = FakeServer()
    _, pending = _start(server)
    restored = connect.ConnectState.from_dict(json.loads(json.dumps(pending.to_dict())))
    assert restored == pending
    assert pending.code_verifier not in repr(pending)
    assert pending.private_jwk["d"] not in repr(pending)


def test_result_repr_hides_the_token() -> None:
    server = FakeServer()
    _, pending = _start(server)
    result = connect.finish(
        pending, code="c" * 43, state=pending.state, http_client=server.client()
    )
    assert result.token not in repr(result)
