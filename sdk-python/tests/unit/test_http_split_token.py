"""Tests SDK ≥0.7 — la dkey ne transite jamais sur le canal HTTP.

Promesse E2E des API keys : le serveur ne doit jamais voir la `decryption_key`
en transit. Le SDK doit donc, à chaque requête, envoyer un token dont le
segment dkey est remplacé par un placeholder.

Ces tests interceptent `httpx.request` au niveau réseau (pas un mock spec=...)
pour avoir la valeur réelle du header `Authorization` envoyé.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from harpocrate.http import VaultHttpClient
from harpocrate.token import parse_token

# Fixtures locales (token complet, format réel hrpv_*)
_TEST_DKEY_BYTES = bytes(range(32))
_TEST_DKEY_B64 = base64.urlsafe_b64encode(_TEST_DKEY_BYTES).rstrip(b"=").decode()
_TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _uuid_to_b32(uid: uuid.UUID) -> str:
    encoded = base64.b32encode(uid.bytes).decode().lower()
    return encoded.rstrip("=")


_TEST_ID_B32 = _uuid_to_b32(_TEST_API_KEY_ID)
_TEST_AUTH_SECRET = "A" * 43
_TEST_HMAC = "B" * 22
_TEST_TOKEN = (
    f"hrpv_1_{_TEST_ID_B32}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
)


def _fake_response(status: int = 200, payload: Any = None) -> MagicMock:
    """Réponse httpx mockée."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = str(payload) if payload is not None else ""
    return resp


@pytest.fixture(autouse=True)
def _allow_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autorise http:// pour les tests."""
    monkeypatch.setenv("HARPOCRATE_ALLOW_INSECURE", "1")


def test_authorization_header_does_not_contain_dkey() -> None:
    """Une requête GET n'envoie pas la dkey dans le header `Authorization`."""
    client = VaultHttpClient(base_url="http://localhost:8000", token=_TEST_TOKEN)

    with patch("httpx.request", return_value=_fake_response(200, {"status": "ok"})) as mock:
        client.get("/v1/health")

    headers = mock.call_args.kwargs["headers"]
    auth = headers["Authorization"]

    assert _TEST_DKEY_B64 not in auth, f"dkey leak dans Authorization : {auth!r}"
    assert auth.startswith("Bearer hrpv_1_"), f"Format Authorization inattendu : {auth!r}"


def test_authorization_header_preserves_auth_secret_and_hmac() -> None:
    """Le segment auth_secret et le HMAC restent intacts (sinon le serveur refuse)."""
    client = VaultHttpClient(base_url="http://localhost:8000", token=_TEST_TOKEN)

    with patch("httpx.request", return_value=_fake_response(200, {})) as mock:
        client.get("/v1/health")

    auth = mock.call_args.kwargs["headers"]["Authorization"]
    bearer_token = auth.removeprefix("Bearer ")
    reparsed = parse_token(bearer_token)

    assert reparsed.auth_secret_b64 == _TEST_AUTH_SECRET
    assert reparsed.hmac_b64 == _TEST_HMAC
    assert reparsed.api_key_id == _TEST_API_KEY_ID
    assert reparsed.permissions == 0x3F


def test_post_put_patch_delete_also_strip_dkey() -> None:
    """Toutes les méthodes HTTP envoient le token tronqué."""
    client = VaultHttpClient(base_url="http://localhost:8000", token=_TEST_TOKEN)

    with patch("httpx.request", return_value=_fake_response(204)) as mock:
        client.post("/v1/x", json={"a": 1})
        client.put("/v1/x", json={"a": 2})
        client.patch("/v1/x", json={"a": 3})
        client.delete("/v1/x")

    for call in mock.call_args_list:
        auth = call.kwargs["headers"]["Authorization"]
        assert _TEST_DKEY_B64 not in auth, f"dkey leak dans {call.args[0]} : {auth!r}"


def test_truncated_token_is_constant_across_requests() -> None:
    """Le token envoyé est identique à chaque requête (pas de re-tirage random)."""
    client = VaultHttpClient(base_url="http://localhost:8000", token=_TEST_TOKEN)

    with patch("httpx.request", return_value=_fake_response(200, {})) as mock:
        client.get("/v1/a")
        client.get("/v1/b")
        client.get("/v1/c")

    auths = [c.kwargs["headers"]["Authorization"] for c in mock.call_args_list]
    assert len(set(auths)) == 1, f"Le token tronqué doit être stable : {auths!r}"


def test_invalid_token_rejected_at_construction() -> None:
    """Instancier VaultHttpClient avec un token malformé lève immédiatement."""
    from harpocrate.exceptions import InvalidTokenError

    with pytest.raises(InvalidTokenError):
        VaultHttpClient(base_url="http://localhost:8000", token="hrpv_garbage")
