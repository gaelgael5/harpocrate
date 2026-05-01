"""Tests endpoint /v1/config/public."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_config_public_returns_floors() -> None:
    from app.main import app

    client = TestClient(app)
    r = client.get("/v1/config/public")
    assert r.status_code == 200
    body = r.json()
    assert body["kdf_floors"] == {
        "memory_kb": 65536,
        "iterations": 3,
        "parallelism": 4,
    }
    assert body["rsa_minimum_key_size"] == 2048
    assert body["passphrase_minimum_length"] == 12
    assert body["audit_retention_days"] == 90
    assert body["version"] == "0.1.0"
    assert "random" in body["supported_generators"]
    assert "rsa_keypair" in body["supported_generators"]
