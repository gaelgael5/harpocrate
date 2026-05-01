"""Tests structlog JSON setup."""

from __future__ import annotations

import base64
import json

import pytest


def test_configure_logging_emits_json(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")

    from app.core.logging import configure_logging, logger

    configure_logging()
    logger.info("event_test", foo="bar")

    out, _ = capfd.readouterr()
    line = out.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "event_test"
    assert parsed["foo"] == "bar"
    assert "timestamp" in parsed
