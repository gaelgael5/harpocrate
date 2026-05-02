"""Tests endpoint GET /v1/apps — menu launcher cross-suite."""
from __future__ import annotations

import base64
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security

    _sec_settings = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec_settings, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec_settings, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec_settings, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _auth_header() -> dict[str, str]:
    token = make_jwt_token()
    return {"Authorization": f"Bearer {token}"}


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_apps_returns_entries_when_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Quand apps.json est valide, les entrées sont retournées."""
    apps_file = tmp_path / "apps.json"
    apps_file.write_text(
        json.dumps(
            {
                "urls": [
                    {
                        "key": "docker",
                        "label": "Docker",
                        "icon": "https://docker-agflow.yoops.org/favicon.ico",
                        "url": "https://docker-agflow.yoops.org/",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    from app.core.config import settings

    monkeypatch.setattr(settings, "apps_file", str(apps_file))

    r = _client().get("/v1/apps", headers=_auth_header())

    assert r.status_code == 200
    body = r.json()
    assert len(body["urls"]) == 1
    entry = body["urls"][0]
    assert entry["key"] == "docker"
    assert entry["label"] == "Docker"
    assert "docker-agflow.yoops.org" in entry["icon"]
    assert "docker-agflow.yoops.org" in entry["url"]


def test_apps_returns_empty_when_file_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Quand apps.json est absent, la réponse est {"urls": []}."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "apps_file", str(tmp_path / "nonexistent.json"))

    r = _client().get("/v1/apps", headers=_auth_header())

    assert r.status_code == 200
    assert r.json() == {"urls": []}


def test_apps_returns_empty_when_json_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Quand apps.json contient du JSON invalide, la réponse est {"urls": []}."""
    apps_file = tmp_path / "apps.json"
    apps_file.write_text("{ this is not valid json !!!", encoding="utf-8")

    from app.core.config import settings

    monkeypatch.setattr(settings, "apps_file", str(apps_file))

    r = _client().get("/v1/apps", headers=_auth_header())

    assert r.status_code == 200
    assert r.json() == {"urls": []}


def test_apps_requires_jwt() -> None:
    """Sans header Authorization, l'endpoint retourne 401."""
    r = _client().get("/v1/apps")
    assert r.status_code == 401


def test_apps_validates_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Une entrée avec une URL invalide → toutes les entrées sont rejetées ({"urls": []})."""
    apps_file = tmp_path / "apps.json"
    apps_file.write_text(
        json.dumps(
            {
                "urls": [
                    {
                        "key": "valid",
                        "label": "Valid App",
                        "icon": "https://valid.example.com/favicon.ico",
                        "url": "https://valid.example.com/",
                    },
                    {
                        "key": "bad",
                        "label": "Bad App",
                        "icon": "not-a-url",
                        "url": "also-not-a-url",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    from app.core.config import settings

    monkeypatch.setattr(settings, "apps_file", str(apps_file))

    r = _client().get("/v1/apps", headers=_auth_header())

    assert r.status_code == 200
    # Sémantique all-or-nothing : une entrée invalide vide tout le menu
    assert r.json() == {"urls": []}
