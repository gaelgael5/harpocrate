"""Sérialisation HTTP de la clé publique éphémère d'une application (JWK, RFC 7517).

Régression 2026-10-20 (vault.yoops.org, application rag) : une JWK reçue sans `use`,
`alg` ni `kid` — c'est ce qu'envoie le SDK Python — revenait de
`GET /v1/connect/requests/{uri}` avec ces membres à `null`. Le front, qui ne les
accepte qu'absents, rejetait la réponse : « Demande impossible à traiter ».
"""

from __future__ import annotations

import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.api.connect_flow import AppPublicJwk, ConnectClientPublic, ConnectRequestView
from tests._connect_helpers import make_jwk


def _served_jwk(jwk: dict[str, str]) -> dict[str, object]:
    """JWK telle que FastAPI la sérialise dans la réponse de GET /v1/connect/requests."""
    app = FastAPI()

    @app.get("/view", response_model=ConnectRequestView)
    def view() -> ConnectRequestView:
        return ConnectRequestView(
            client=ConnectClientPublic(client_id="rag", name="rag", description=None),
            redirect_uri="https://rag.example/cb",
            requested_permissions=1,
            requested_ttl_days=None,
            app_public_jwk=AppPublicJwk.model_validate(jwk),
            expires_at=datetime.datetime(2026, 10, 20, tzinfo=datetime.UTC),
        )

    served: dict[str, object] = TestClient(app).get("/view").json()["app_public_jwk"]
    return served


def test_served_jwk_without_optional_members_has_no_null_member() -> None:
    _, jwk = make_jwk()
    assert _served_jwk(jwk) == jwk


def test_served_jwk_keeps_optional_members_when_provided() -> None:
    _, jwk = make_jwk()
    jwk_full = {**jwk, "use": "enc", "alg": "ECDH-ES", "kid": "app-key-1"}
    assert _served_jwk(jwk_full) == jwk_full


def test_jwk_dump_for_storage_has_no_null_member() -> None:
    _, jwk = make_jwk()
    assert AppPublicJwk.model_validate(jwk).model_dump(mode="json") == jwk
