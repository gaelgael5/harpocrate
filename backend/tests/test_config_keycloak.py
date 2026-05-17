"""Tests endpoint /v1/config/keycloak."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pas de reload de app.core.config — ça créerait un nouvel objet settings
    # dont les autres modules ne voient pas (ils ont fait `from app.core.config
    # import settings` au moment de leur import → référence stale).
    # À la place, on modifie l'instance partagée avec setattr (cleanup auto
    # via monkeypatch en fin de test).
    import app.core.config

    settings = app.core.config.settings
    monkeypatch.setattr(settings, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(settings, "keycloak_realm", "yoops")
    monkeypatch.setattr(settings, "keycloak_client_id", "harpocrate-vault")
    monkeypatch.setattr(settings, "public_url", "https://t")


def test_config_keycloak_exposes_realm_and_urls() -> None:
    from app.main import app

    client = TestClient(app)
    r = client.get("/v1/config/keycloak")
    assert r.status_code == 200
    body = r.json()
    assert body["realm"] == "yoops"
    assert body["client_id"] == "harpocrate-vault"
    assert body["auth_url"] == "https://keycloak.yoops.org/realms/yoops"
    assert body["token_url"].endswith("/protocol/openid-connect/token")
    assert body["jwks_url"].endswith("/protocol/openid-connect/certs")
    assert body["issuer"] == body["auth_url"]
