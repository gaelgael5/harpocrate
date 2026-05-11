"""Tests endpoint WebSocket /v1/admin/ssh-terminal/ws (LOT 1)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _build_test_app() -> FastAPI:
    from app.api.v1 import admin_ssh_terminal

    app = FastAPI()
    app.include_router(admin_ssh_terminal.router)
    return app


def test_ws_rejects_missing_token() -> None:
    app = _build_test_app()
    client = TestClient(app)
    with (
        pytest.raises((WebSocketDisconnect, RuntimeError)),
        client.websocket_connect("/admin/ssh-terminal/ws"),
    ):
        pass


def test_ws_rejects_invalid_token() -> None:
    app = _build_test_app()
    client = TestClient(app)
    with (
        pytest.raises((WebSocketDisconnect, RuntimeError)),
        client.websocket_connect("/admin/ssh-terminal/ws?token=not_a_real_jwt"),
    ):
        pass


def test_ws_rejects_api_key_token() -> None:
    app = _build_test_app()
    client = TestClient(app)
    with (
        pytest.raises((WebSocketDisconnect, RuntimeError)),
        client.websocket_connect("/admin/ssh-terminal/ws?token=hrpv_fake_api_key"),
    ):
        pass
