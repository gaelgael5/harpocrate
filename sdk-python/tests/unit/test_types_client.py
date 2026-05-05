"""Tests P3 — TypesClient : accès au catalogue /v1/secret-types via API key."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

from harpocrate.client import TypesClient
from harpocrate.http import VaultHttpClient
from harpocrate.models import SecretType


def _mock_http_with_responses(responses: dict[str, Any]) -> MagicMock:
    mock_http = MagicMock(spec=VaultHttpClient)

    def fake_get(path: str, **kwargs: Any) -> Any:
        if path in responses:
            return responses[path]
        raise AssertionError(f"unexpected path {path}")

    mock_http.get.side_effect = fake_get
    return mock_http


def test_types_list_returns_list_of_secret_type() -> None:
    """`client.types.list()` retourne une liste de SecretType."""
    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    http = _mock_http_with_responses(
        {
            "/v1/secret-types": {
                "types": [
                    {
                        "type_uuid": str(type_uuid),
                        "type": "raw",
                        "sous_type": "raw",
                        "label": "Raw",
                        "description": None,
                        "is_system": True,
                        "deprecated_at": None,
                        "current_version": {
                            "version_uuid": str(version_uuid),
                            "version": 1,
                            "created_at": "2026-01-01T00:00:00",
                        },
                        "used_by_secrets_count": 5,
                    },
                ],
            },
        }
    )

    client = TypesClient(http=http)
    types = client.list()

    assert len(types) == 1
    assert isinstance(types[0], SecretType)
    assert types[0].type_uuid == type_uuid
    assert types[0].type == "raw"
    assert types[0].sous_type == "raw"
    assert types[0].is_system is True
    assert types[0].used_by_secrets_count == 5
    assert types[0].current_version is not None
    assert types[0].current_version.version_uuid == version_uuid


def test_types_get_returns_full_type_with_schemas() -> None:
    """`client.types.get(uuid)` retourne le SecretType avec schema_data + schema_ui complets."""
    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    http = _mock_http_with_responses(
        {
            f"/v1/secret-types/{type_uuid}": {
                "type_uuid": str(type_uuid),
                "type": "raw",
                "sous_type": "raw",
                "label": "Raw",
                "description": None,
                "is_system": True,
                "deprecated_at": None,
                "current_version": {
                    "version_uuid": str(version_uuid),
                    "version": 1,
                    "created_at": "2026-01-01T00:00:00",
                },
                "current_version_full": {
                    "version_uuid": str(version_uuid),
                    "version": 1,
                    "schema_data": {"type": "object", "properties": {"value": {"type": "string"}}},
                    "schema_ui": {"value": {"widget": "password"}},
                    "created_at": "2026-01-01T00:00:00",
                },
                "all_versions": [
                    {
                        "version_uuid": str(version_uuid),
                        "parent_uuid": str(type_uuid),
                        "version": 1,
                        "schema_data": {"type": "object"},
                        "schema_ui": {},
                        "notes": None,
                        "created_at": "2026-01-01T00:00:00",
                    },
                ],
                "used_by_secrets_count": 5,
            },
        }
    )

    client = TypesClient(http=http)
    secret_type = client.get(type_uuid)

    assert secret_type.type_uuid == type_uuid
    assert secret_type.current_version is not None
    assert secret_type.current_version.schema_data == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }
    assert secret_type.current_version.schema_ui == {"value": {"widget": "password"}}
    assert len(secret_type.all_versions) == 1


def test_types_list_with_query_passes_q_param() -> None:
    """`client.types.list(q='password')` passe q en query string."""
    http = MagicMock(spec=VaultHttpClient)
    http.get.return_value = {"types": []}
    client = TypesClient(http=http)
    client.list(q="password")
    http.get.assert_called_once_with("/v1/secret-types", q="password")
