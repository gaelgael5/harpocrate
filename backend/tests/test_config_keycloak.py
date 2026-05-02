"""Tests endpoint /v1/config/keycloak."""
from __future__ import annotations

import base64
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "harpocrate-vault")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")

    # Reload config modules to pick up the new env values
    import app.api.v1.config_keycloak as ck_mod
    import app.core.config

    importlib.reload(app.core.config)
    importlib.reload(ck_mod)


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
