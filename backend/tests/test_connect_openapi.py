"""Contrat OpenAPI du flux « Se connecter avec Harpocrate » (feature 7).

Le contrat publié aux applications ne contient QUE ce qu'elles appellent : le dépôt PAR et
l'échange du code. Les routes du navigateur et de l'admin n'en font pas partie.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_connect_contract_lists_only_application_routes(client: AsyncClient) -> None:
    r = await client.get("/v1/openapi-connect.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.1")
    assert {p: sorted(m) for p, m in spec["paths"].items()} == {
        "/v1/connect/par": ["post"],
        "/v1/connect/token": ["post"],
    }
    par_body = spec["components"]["schemas"]["ConnectParRequest"]
    assert {"code_challenge", "app_public_jwk", "redirect_uri"} <= set(par_body["properties"])


async def test_api_key_contract_does_not_expose_the_connect_flow(client: AsyncClient) -> None:
    r = await client.get("/v1/openapi-api-key.json")
    assert r.status_code == 200
    assert not any(p.startswith("/v1/connect") for p in r.json()["paths"])
