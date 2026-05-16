"""Tests endpoint GET /admin/install-mode."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_test_app() -> tuple[TestClient, FastAPI, object]:
    from app.api.v1.admin_install_mode import router
    from app.core.admin_auth import require_admin_jwt
    from app.services import install_mode as svc

    class _FakeAdmin:
        user_id = None

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[require_admin_jwt] = lambda: _FakeAdmin()
    return TestClient(app), app, svc


def test_install_mode_endpoint_returns_detected_mode() -> None:
    from app.services import install_mode as mod

    client, _app, _svc = _build_test_app()
    fake = mod.InstallModeInfo(
        mode="docker_compose_auto",
        docker_socket_accessible=True,
        pg_container_data_host_path=None,
    )
    with patch.object(mod, "detect", return_value=fake):
        resp = client.get("/v1/admin/install-mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "docker_compose_auto"
    assert body["docker_socket_accessible"] is True


def test_install_mode_endpoint_requires_admin() -> None:
    """Sans override de require_admin_jwt → 401/403."""
    from app.api.v1.admin_install_mode import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/admin/install-mode")
    # Le default require_admin_jwt n'est pas mocké → l'auth doit échouer
    assert resp.status_code in (401, 403, 422)
