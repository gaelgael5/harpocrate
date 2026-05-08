"""Tests repository system_metadata — symétrie set_value / get_value.

Régression : un bug a livré des clés AGE corrompues car set_value sérialisait
en JSON (json.dumps) tandis que get_value renvoyait la valeur jsonb brute
d'asyncpg (chaîne JSON, donc avec guillemets). Cf. erreur :
    age: error: unknown recipient type: "\"age1xxx...\""
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.db.repositories import system_metadata as meta_repo


@pytest.mark.asyncio
async def test_get_value_decodes_json_string_back_to_python_str() -> None:
    """Une clé stockée comme str doit être relue comme str (sans guillemets)."""
    conn = AsyncMock()
    # asyncpg renvoie la valeur jsonb sous forme de chaîne JSON brute si aucun
    # codec custom n'est enregistré. C'est ce qu'on simule ici.
    conn.fetchrow = AsyncMock(return_value={"value": json.dumps("age1xxx")})

    value = await meta_repo.get_value(conn, "age_public_key")

    assert value == "age1xxx"
    assert not value.startswith('"')


@pytest.mark.asyncio
async def test_get_value_decodes_json_object_back_to_python_dict() -> None:
    """Un dict stocké doit être relu comme dict (pas comme chaîne JSON)."""
    conn = AsyncMock()
    payload = {"active": True, "reason": "upgrade"}
    conn.fetchrow = AsyncMock(return_value={"value": json.dumps(payload)})

    value = await meta_repo.get_value(conn, "maintenance_mode")

    assert value == payload


@pytest.mark.asyncio
async def test_get_value_returns_none_when_row_missing() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    assert await meta_repo.get_value(conn, "absent") is None


@pytest.mark.asyncio
async def test_get_value_passes_through_already_decoded_value() -> None:
    """Si asyncpg a un codec qui désérialise déjà, on ne re-décode pas."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"value": {"already": "dict"}})

    value = await meta_repo.get_value(conn, "x")

    assert value == {"already": "dict"}


@pytest.mark.asyncio
async def test_get_value_falls_back_to_raw_when_invalid_json() -> None:
    """Robustesse : si la valeur n'est pas du JSON, on retourne la chaîne brute."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"value": "not-json{"})

    assert await meta_repo.get_value(conn, "x") == "not-json{"
