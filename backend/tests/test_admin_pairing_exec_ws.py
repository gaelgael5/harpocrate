"""Tests endpoint WebSocket pairing exec."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _build_test_app() -> tuple[TestClient, FastAPI]:
    from app.api.v1.admin_pairing_exec import router
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    return TestClient(app), app


def test_ws_rejects_invalid_jwt() -> None:
    """Token invalide → WS close avec code policy_violation."""
    client, _app = _build_test_app()
    sid = uuid4()
    url = f"/v1/admin/replication/pairing/{sid}/exec/ws?token=invalid"
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(url):
        pass
