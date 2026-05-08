"""Tests du client Novu (LOT_57.A)."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _set_novu_key(monkeypatch: pytest.MonkeyPatch, key: str = "test-key") -> None:
    """Mute la `settings` existante au lieu de la rebinder.

    Un `app.core.config.settings = Settings()` ne se propage PAS aux modules
    qui ont fait `from app.core.config import settings` (le binding local
    reste sur l'ancien objet). Muter l'attribut sur l'instance existante
    permet aux callers de voir la nouvelle valeur sans réimport.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "novu_api_key", key)
    monkeypatch.setattr(settings, "novu_api_url", "https://api.novu.co/v1")


def _set_novu_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "novu_api_key", "")


@pytest.mark.asyncio
async def test_no_op_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_novu_unconfigured(monkeypatch)
    from app.services import notify_novu

    # Pas de clé → pas d'appel HTTP, pas d'erreur.
    with patch("httpx.AsyncClient") as mock_client:
        await notify_novu.trigger_event(
            "passphrase-reset",
            subscriber_id="user-1",
            email="x@y",
            payload={"k": "v"},
        )
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_raises_when_unconfigured_and_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_novu_unconfigured(monkeypatch)
    from app.services import notify_novu

    with pytest.raises(notify_novu.NovuNotConfiguredError):
        await notify_novu.trigger_event(
            "passphrase-reset",
            subscriber_id="user-1",
            email="x@y",
            payload={},
            raise_if_unconfigured=True,
        )


@pytest.mark.asyncio
async def test_posts_correct_body_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_novu_key(monkeypatch, "secret-key")
    from app.services import notify_novu

    captured: dict[str, object] = {}

    async def fake_post(url: str, json: dict[str, object], headers: dict[str, str]):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        resp = httpx.Response(200, json={"acknowledged": True})
        return resp

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=fake_client):
        await notify_novu.trigger_event(
            "passphrase-reset",
            subscriber_id="user-42",
            email="g@example.com",
            payload={"firstName": "Gael", "resetLink": "https://x/r/abc"},
        )

    assert captured["url"] == "https://api.novu.co/v1/events/trigger"
    body = captured["json"]
    assert body == {
        "name": "passphrase-reset",
        "to": {"subscriberId": "user-42", "email": "g@example.com"},
        "payload": {"firstName": "Gael", "resetLink": "https://x/r/abc"},
    }
    headers = captured["headers"]
    assert headers["Authorization"] == "ApiKey secret-key"


@pytest.mark.asyncio
async def test_swallows_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un 5xx Novu ne doit pas casser le caller."""
    _set_novu_key(monkeypatch)
    from app.services import notify_novu

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(return_value=httpx.Response(500, text="boom"))

    with patch("httpx.AsyncClient", return_value=fake_client):
        # Aucune exception ne doit remonter.
        await notify_novu.trigger_event(
            "passphrase-reset",
            subscriber_id="u",
            email="e@e",
            payload={},
        )


@pytest.mark.asyncio
async def test_swallows_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_novu_key(monkeypatch)
    from app.services import notify_novu

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("dns fail"))

    with patch("httpx.AsyncClient", return_value=fake_client):
        await notify_novu.trigger_event(
            "passphrase-reset",
            subscriber_id="u",
            email="e@e",
            payload={},
        )
