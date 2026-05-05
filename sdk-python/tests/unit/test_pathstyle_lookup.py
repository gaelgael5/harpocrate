"""Tests P3 — SecretsClient route les opérations unitaires sur des noms à '/'
via le lookup interne (list par path) puis via les routes /by-id/{sid}.
"""

from __future__ import annotations

import base64
import uuid
from contextlib import suppress
from typing import Any
from unittest.mock import MagicMock

from harpocrate.cache import WalletKeyCache
from harpocrate.client import SecretsClient
from harpocrate.http import VaultHttpClient
from harpocrate.token import parse_token

_TEST_DKEY_BYTES = bytes(range(32))
_TEST_DKEY_B64 = base64.urlsafe_b64encode(_TEST_DKEY_BYTES).rstrip(b"=").decode()
_TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_WALLET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_TEST_AUTH_SECRET = "A" * 43
_TEST_HMAC = "B" * 22


def _uuid_to_b32(uid: uuid.UUID) -> str:
    return base64.b32encode(uid.bytes).decode().lower().rstrip("=")


_TEST_TOKEN = f"hrpv_1_{_uuid_to_b32(_TEST_API_KEY_ID)}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"


def _make_secrets_client(responses: dict[str, Any]) -> tuple[SecretsClient, MagicMock]:
    http = MagicMock(spec=VaultHttpClient)

    def fake_get(url: str, **kwargs: Any) -> Any:
        if url in responses:
            return responses[url]
        raise AssertionError(f"unexpected GET {url}")

    def fake_delete(url: str) -> None:
        if url not in responses.get("__delete_paths__", []):
            raise AssertionError(f"unexpected DELETE {url}")

    http.get.side_effect = fake_get
    http.delete.side_effect = fake_delete

    parsed = parse_token(_TEST_TOKEN)
    cache = WalletKeyCache(ttl_seconds=600)
    sc = SecretsClient(
        http=http,
        wallet_id=_TEST_WALLET_ID,
        parsed_token=parsed,
        cache=cache,
    )
    return sc, http


def test_simple_name_uses_name_based_route_directly() -> None:
    """Un nom sans '/' est appelé directement via la route name-based (1 requête, pas de lookup)."""
    secret_id = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
    responses = {
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets/MY_KEY": {
            "id": str(secret_id),
            "name": "MY_KEY",
            "encrypted_value": base64.b64encode(b"x").decode(),
            "encrypted_wallet_key": base64.b64encode(b"y").decode(),
            "is_placeholder": False,
            "generation_version": 1,
            "tags": [],
        },
        "__delete_paths__": [f"/v1/wallets/{_TEST_WALLET_ID}/secrets/MY_KEY"],
    }
    sc, http = _make_secrets_client(responses)

    sc.delete("MY_KEY")
    # Vérifie qu'aucun appel à /secrets?path= n'a été fait (donc pas de lookup pour les noms simples)
    list_calls = [
        c for c in http.get.call_args_list if c.args[0].endswith("/secrets") and "path" in c.kwargs
    ]
    assert list_calls == []


def test_pathstyle_name_resolves_id_then_calls_by_id_for_delete() -> None:
    """Un nom à '/' déclenche un lookup (list par path) puis appelle /by-id/{sid}."""
    secret_id = uuid.UUID("dddddddd-0000-0000-0000-000000000099")
    name = "/users/no_email/api-1"
    parent_path = "/users/no_email/"

    responses = {
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets": {
            "secrets": [
                {
                    "id": str(secret_id),
                    "name": name,
                    "is_placeholder": False,
                    "generation_version": 1,
                    "tags": [],
                    "description": None,
                    "created_at": "2026-01-01",
                    "updated_at": "2026-01-01",
                },
            ],
            "next_cursor": None,
        },
        "__delete_paths__": [f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}"],
    }
    sc, http = _make_secrets_client(responses)

    sc.delete(name)

    # Vérifie qu'on a fait un GET /secrets?path=/users/no_email/ pour résoudre l'ID
    list_calls = [c for c in http.get.call_args_list if c.kwargs.get("path") == parent_path]
    assert len(list_calls) == 1, f"attendu 1 appel list, eu {len(list_calls)}"

    # Vérifie qu'on a fait un DELETE /secrets/by-id/{secret_id}
    delete_calls = list(http.delete.call_args_list)
    assert len(delete_calls) == 1
    assert delete_calls[0].args[0] == f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}"


def test_pathstyle_name_resolves_id_then_calls_by_id_for_get() -> None:
    """get(name) avec un nom à '/' fait lookup puis appelle /by-id/{sid}."""
    secret_id = uuid.UUID("dddddddd-0000-0000-0000-000000000099")
    name = "/users/no_email/api-1"
    parent_path = "/users/no_email/"

    # Encoded value : utilisons la wallet_key déchiffrable pour faire passer la décryption
    # (simplification : on vérifie juste l'URL appelée, pas le déchiffrement complet)
    responses = {
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets": {
            "secrets": [
                {
                    "id": str(secret_id),
                    "name": name,
                    "is_placeholder": False,
                    "generation_version": 1,
                    "tags": [],
                    "description": None,
                    "created_at": "2026-01-01",
                    "updated_at": "2026-01-01",
                },
            ],
            "next_cursor": None,
        },
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}": {
            "id": str(secret_id),
            "name": name,
            "encrypted_value": base64.b64encode(b"x").decode(),
            "encrypted_wallet_key": base64.b64encode(b"y").decode(),
            "is_placeholder": False,
            "generation_version": 1,
            "tags": [],
        },
    }
    sc, http = _make_secrets_client(responses)

    # On ne déchiffre pas (nécessite mock crypto), on vérifie juste l'URL
    with suppress(Exception):  # déchiffrement échouera, c'est OK — on vérifie les appels HTTP
        sc.get(name)

    # Vérifie : 1 list (lookup) + 1 GET by-id
    list_calls = [c for c in http.get.call_args_list if c.kwargs.get("path") == parent_path]
    assert len(list_calls) == 1
    by_id_calls = [c for c in http.get.call_args_list if "by-id" in c.args[0]]
    assert len(by_id_calls) == 1
    assert by_id_calls[0].args[0] == f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}"
