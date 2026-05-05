"""Tests P3 — create() et create_placeholder() acceptent un type_uuid optionnel."""

from __future__ import annotations

import base64
import uuid
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


def _make_sc() -> tuple[SecretsClient, MagicMock]:
    http = MagicMock(spec=VaultHttpClient)
    parsed = parse_token(_TEST_TOKEN)
    cache = WalletKeyCache(ttl_seconds=600)
    # Pré-cache la wallet_key pour éviter le wallet_key fetch
    cache.set(str(_TEST_WALLET_ID), _TEST_DKEY_BYTES)
    sc = SecretsClient(
        http=http,
        wallet_id=_TEST_WALLET_ID,
        parsed_token=parsed,
        cache=cache,
    )
    return sc, http


def test_create_without_type_uuid_omits_field_in_body() -> None:
    """create(name, value) sans type_uuid → body n'a pas la clé."""
    sc, http = _make_sc()
    http.post.return_value = {"secret_id": str(uuid.uuid4())}

    sc.create("MY_KEY", "secret_value")

    call = http.post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert "type_uuid" not in body
    assert "schema_version_uuid" not in body


def test_create_with_type_uuid_includes_field() -> None:
    """create(name, value, type_uuid=X) → body contient type_uuid=X."""
    sc, http = _make_sc()
    http.post.return_value = {"secret_id": str(uuid.uuid4())}

    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    schema_version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000001")

    sc.create(
        "MY_KEY", "secret_value", type_uuid=type_uuid, schema_version_uuid=schema_version_uuid
    )

    call = http.post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert body["type_uuid"] == str(type_uuid)
    assert body["schema_version_uuid"] == str(schema_version_uuid)


def test_create_placeholder_with_type_uuid_includes_field() -> None:
    """create_placeholder(...) avec type_uuid → body contient type_uuid."""
    sc, http = _make_sc()
    http.post.return_value = {"secret_id": str(uuid.uuid4())}

    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    sc.create_placeholder(
        "MY_KEY",
        descriptor={"type": "random", "length": 32, "encoding": "base64"},
        type_uuid=type_uuid,
    )

    call = http.post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert body["type_uuid"] == str(type_uuid)
