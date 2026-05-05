"""Tests du VaultClient avec mocks httpx — LOT_09 SDK."""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any
from unittest.mock import MagicMock

from harpocrate.cache import WalletKeyCache
from harpocrate.client import SecretsClient
from harpocrate.crypto.aes_gcm import aes_gcm_decrypt, aes_gcm_encrypt
from harpocrate.exceptions import (
    SecretNotFound,
)
from harpocrate.http import VaultHttpClient
from harpocrate.token import parse_token

# Token de test (même que conftest.py)
_TEST_DKEY_BYTES = bytes(range(32))
_TEST_DKEY_B64 = base64.urlsafe_b64encode(_TEST_DKEY_BYTES).rstrip(b"=").decode()
_TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_WALLET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_TEST_AUTH_SECRET = "A" * 43
_TEST_HMAC = "B" * 22


def _uuid_to_b32(uid: uuid.UUID) -> str:
    encoded = base64.b32encode(uid.bytes).decode().lower()
    return encoded.rstrip("=")


_TEST_ID_B32 = _uuid_to_b32(_TEST_API_KEY_ID)
_TEST_TOKEN = f"hrpv_1_{_TEST_ID_B32}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"


def _make_mock_http(responses: dict[str, Any]) -> MagicMock:
    """Crée un mock VaultHttpClient retournant des réponses prédéfinies."""
    mock_http = MagicMock(spec=VaultHttpClient)

    def fake_get(path: str, **kwargs: Any) -> Any:
        if path in responses:
            return responses[path]
        raise SecretNotFound(f"Mock: path not found: {path}")

    def fake_post(path: str, json: Any = None) -> Any:  # noqa: ARG001
        if path in responses:
            return responses[path]
        raise SecretNotFound(f"Mock: path not found: {path}")

    mock_http.get.side_effect = fake_get
    mock_http.post.side_effect = fake_post
    return mock_http


def _make_secrets_client(
    mock_http: MagicMock,
    wallet_key: bytes | None = None,
) -> SecretsClient:
    """Crée un SecretsClient avec mock HTTP et wallet_key pré-chargée."""
    parsed = parse_token(_TEST_TOKEN)
    cache = WalletKeyCache()

    if wallet_key is not None:
        # Pré-charge la wallet_key dans le cache
        cache.set(str(_TEST_WALLET_ID), wallet_key)

    return SecretsClient(
        http=mock_http,
        wallet_id=_TEST_WALLET_ID,
        parsed_token=parsed,
        cache=cache,
    )


class TestSecretsClientGet:
    """Tests de SecretsClient.get()."""

    def test_get_decrypts_correctly(self) -> None:
        """get() déchiffre correctement un secret."""
        wallet_key = os.urandom(32)
        plaintext = "my-secret-value"
        enc_value = aes_gcm_encrypt(plaintext.encode(), wallet_key)
        # Pour le test, encrypted_wallet_key n'est pas utilisé (wallet_key dans cache)
        enc_wk = aes_gcm_encrypt(wallet_key, _TEST_DKEY_BYTES)

        path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets/MY_SECRET"
        mock_http = _make_mock_http(
            {
                path: {
                    "id": str(uuid.uuid4()),
                    "name": "MY_SECRET",
                    "encrypted_value": base64.b64encode(enc_value).decode(),
                    "encrypted_wallet_key": base64.b64encode(enc_wk).decode(),
                    "description": None,
                    "tags": [],
                    "is_placeholder": False,
                    "generation_version": 1,
                }
            }
        )

        client = _make_secrets_client(mock_http, wallet_key=wallet_key)
        result = client.get("MY_SECRET")
        assert result == plaintext

    def test_get_uses_cache_for_wallet_key(self) -> None:
        """get() utilise la wallet_key du cache sans appel réseau supplémentaire."""
        wallet_key = os.urandom(32)
        plaintext = "cached-secret"
        enc_value = aes_gcm_encrypt(plaintext.encode(), wallet_key)
        enc_wk = aes_gcm_encrypt(wallet_key, _TEST_DKEY_BYTES)

        path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets/CACHED"
        mock_http = _make_mock_http(
            {
                path: {
                    "id": str(uuid.uuid4()),
                    "name": "CACHED",
                    "encrypted_value": base64.b64encode(enc_value).decode(),
                    "encrypted_wallet_key": base64.b64encode(enc_wk).decode(),
                    "description": None,
                    "tags": [],
                    "is_placeholder": False,
                    "generation_version": 1,
                }
            }
        )

        client = _make_secrets_client(mock_http, wallet_key=wallet_key)
        # Appel 1
        r1 = client.get("CACHED")
        # Appel 2 (doit utiliser le cache)
        r2 = client.get("CACHED")
        assert r1 == r2 == plaintext

    def test_get_fetches_wallet_key_when_not_cached(self) -> None:
        """get() récupère la wallet_key depuis le serveur si absente du cache."""
        wallet_key = os.urandom(32)
        plaintext = "fetched-from-server"
        enc_value = aes_gcm_encrypt(plaintext.encode(), wallet_key)
        enc_wk_for_grant = aes_gcm_encrypt(wallet_key, _TEST_DKEY_BYTES)

        grant_path = f"/v1/wallets/{_TEST_WALLET_ID}/my-api-key-grant"
        secret_path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets/FETCHED"
        mock_http = _make_mock_http(
            {
                grant_path: {
                    "encrypted_wallet_key": base64.b64encode(enc_wk_for_grant).decode(),
                },
                secret_path: {
                    "id": str(uuid.uuid4()),
                    "name": "FETCHED",
                    "encrypted_value": base64.b64encode(enc_value).decode(),
                    "encrypted_wallet_key": base64.b64encode(enc_wk_for_grant).decode(),
                    "description": None,
                    "tags": [],
                    "is_placeholder": False,
                    "generation_version": 1,
                },
            }
        )

        # Pas de wallet_key dans le cache
        client = _make_secrets_client(mock_http, wallet_key=None)
        result = client.get("FETCHED")
        assert result == plaintext


class TestSecretsClientList:
    """Tests de SecretsClient.list_secrets()."""

    def test_list_returns_secret_infos(self) -> None:
        """list() retourne une liste de SecretInfo."""
        path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets"
        mock_http = _make_mock_http(
            {
                path: {
                    "secrets": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "SECRET_A",
                            "description": None,
                            "tags": [],
                            "is_placeholder": False,
                            "generation_version": 1,
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "name": "PLACEHOLDER_B",
                            "description": None,
                            "tags": [],
                            "is_placeholder": True,
                            "generation_version": 0,
                        },
                    ],
                    "next_cursor": None,
                }
            }
        )

        client = _make_secrets_client(mock_http)
        resp = client.list_secrets()
        assert len(resp.secrets) == 2
        assert resp.secrets[0].name == "SECRET_A"
        assert not resp.secrets[0].is_placeholder
        assert resp.secrets[1].name == "PLACEHOLDER_B"
        assert resp.secrets[1].is_placeholder


class TestSecretsClientPopulate:
    """Tests de SecretsClient.populate()."""

    def test_populate_auto_generate_calls_descriptor(self) -> None:
        """populate(auto_generate=True) récupère le descripteur et génère."""
        wallet_key = os.urandom(32)
        # Pré-charge le grant
        enc_wk_for_grant = aes_gcm_encrypt(wallet_key, _TEST_DKEY_BYTES)

        descriptor_path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets/DB_PWD/descriptor"
        populate_path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets/DB_PWD/populate"
        grant_path = f"/v1/wallets/{_TEST_WALLET_ID}/my-api-key-grant"

        mock_http = _make_mock_http(
            {
                descriptor_path: {
                    "name": "DB_PWD",
                    "generation_descriptor": {
                        "type": "random",
                        "length": 24,
                        "charset": "alphanum",
                    },
                },
                populate_path: {"generation_version": 1},
                grant_path: {"encrypted_wallet_key": base64.b64encode(enc_wk_for_grant).decode()},
            }
        )

        client = _make_secrets_client(mock_http, wallet_key=wallet_key)
        result = client.populate("DB_PWD", auto_generate=True)
        assert result.success
        assert result.name == "DB_PWD"

    def test_populate_with_explicit_value(self) -> None:
        """populate(auto_generate=False, value=...) utilise la valeur fournie."""
        wallet_key = os.urandom(32)
        populate_path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets/MY_SECRET/populate"
        mock_http = _make_mock_http(
            {
                populate_path: {"generation_version": 2},
            }
        )

        client = _make_secrets_client(mock_http, wallet_key=wallet_key)
        result = client.populate("MY_SECRET", auto_generate=False, value="explicit-value")
        assert result.success
        assert result.generation_version == 2

    def test_populate_verifies_encrypted_value(self) -> None:
        """populate() envoie une valeur chiffrable (non vide, format correct)."""
        wallet_key = os.urandom(32)
        captured_bodies: list[Any] = []

        parsed = parse_token(_TEST_TOKEN)
        cache = WalletKeyCache()
        cache.set(str(_TEST_WALLET_ID), wallet_key)

        mock_http = MagicMock(spec=VaultHttpClient)
        mock_http.get.return_value = {
            "generation_descriptor": {"type": "random", "length": 16, "charset": "alphanum"}
        }

        def capture_post(path: str, json: Any = None) -> Any:  # noqa: ARG001
            captured_bodies.append(json)
            return {"generation_version": 1}

        mock_http.post.side_effect = capture_post

        client = SecretsClient(
            http=mock_http,
            wallet_id=_TEST_WALLET_ID,
            parsed_token=parsed,
            cache=cache,
        )
        client.populate("SECRET", auto_generate=True)

        assert len(captured_bodies) == 1
        body = captured_bodies[0]
        assert "encrypted_value" in body
        # Le blob doit être déchiffrable avec wallet_key
        blob = base64.b64decode(body["encrypted_value"])
        plain = aes_gcm_decrypt(blob, wallet_key)
        assert len(plain) == 16  # longueur conforme au descripteur


class TestSecretsClientPopulateAll:
    """Tests de SecretsClient.populate_all()."""

    def test_populate_all_only_placeholders(self) -> None:
        """populate_all() n'essaie de peupler que les placeholders."""
        wallet_key = os.urandom(32)
        parsed = parse_token(_TEST_TOKEN)
        cache = WalletKeyCache()
        cache.set(str(_TEST_WALLET_ID), wallet_key)

        list_path = f"/v1/wallets/{_TEST_WALLET_ID}/secrets"
        mock_http = MagicMock(spec=VaultHttpClient)

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path == list_path:
                return {
                    "secrets": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "VALUED",
                            "description": None,
                            "tags": [],
                            "is_placeholder": False,
                            "generation_version": 1,
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "name": "PLACEHOLDER",
                            "description": None,
                            "tags": [],
                            "is_placeholder": True,
                            "generation_version": 0,
                        },
                    ],
                    "next_cursor": None,
                }
            # Descripteur pour PLACEHOLDER
            return {
                "generation_descriptor": {"type": "random", "length": 16, "charset": "alphanum"}
            }

        mock_http.get.side_effect = fake_get
        mock_http.post.return_value = {"generation_version": 1}

        client = SecretsClient(
            http=mock_http,
            wallet_id=_TEST_WALLET_ID,
            parsed_token=parsed,
            cache=cache,
        )
        results = client.populate_all()
        # Seulement PLACEHOLDER doit être dans les résultats
        assert len(results) == 1
        assert results[0].name == "PLACEHOLDER"
        assert results[0].success
