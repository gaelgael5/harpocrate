"""Tests du client listmonk (LOT_57)."""
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


def _enable_listmonk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mute le settings singleton (mutate l'instance, pas rebind) pour
    que `from app.core.config import settings` dans notify_listmonk voie
    bien la config active."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "listmonk_url", "http://listmonk.test:9000")
    monkeypatch.setattr(settings, "listmonk_user", "harpocrate-api")
    monkeypatch.setattr(settings, "listmonk_token", "secret-token")
    monkeypatch.setattr(settings, "listmonk_template_recovery_en", 5)
    monkeypatch.setattr(settings, "listmonk_template_recovery_fr", 4)


def _disable_listmonk(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "listmonk_url", "")


@pytest.mark.asyncio
async def test_no_op_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    with patch("httpx.AsyncClient") as mock_client:
        ok = await notify_listmonk.trigger_recovery(
            email="x@y",
            tx_id="tx-1",
            payload={},
        )
    assert ok is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_raises_when_unconfigured_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    with pytest.raises(notify_listmonk.ListmonkNotConfiguredError):
        await notify_listmonk.trigger_recovery(
            email="x@y",
            tx_id="tx-1",
            payload={},
            raise_if_unconfigured=True,
        )


@pytest.mark.asyncio
async def test_posts_correct_body_and_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    captured: dict[str, object] = {}

    async def fake_post(url: str, json: dict[str, object], headers: dict[str, str]):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(200, json={"data": {}})

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            email="g@example.com",
            tx_id="tx-abc",
            payload={"recoveryLink": "https://x/r/abc", "expiresInMinutes": "30"},
        )
    assert ok is True
    assert captured["url"] == "http://listmonk.test:9000/api/tx"
    body = captured["json"]
    assert body == {
        "subscriber_email": "g@example.com",
        "template_id": 5,  # default EN
        "data": {"recoveryLink": "https://x/r/abc", "expiresInMinutes": "30"},
        "headers": [{"X-Harpocrate-Tx-Id": "tx-abc"}],
    }
    assert captured["headers"]["Authorization"] == "token harpocrate-api:secret-token"


@pytest.mark.asyncio
async def test_uses_fr_template_when_locale_fr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Locale `fr` → template_id 4 (vs 5 par défaut EN)."""
    _enable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    captured_body: dict[str, object] = {}

    async def fake_post(url: str, json: dict[str, object], headers: dict[str, str]):
        captured_body.update(json)
        return httpx.Response(200, json={})

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=fake_client):
        await notify_listmonk.trigger_recovery(
            email="g@example.com",
            tx_id="tx-1",
            payload={},
            locale="fr",
        )
    assert captured_body["template_id"] == 4


@pytest.mark.asyncio
async def test_locale_normalization_region_variants_match_fr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`fr-FR`, `fr_FR` → matchent toujours le template FR."""
    _enable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    captured: list[int] = []

    async def fake_post(url: str, json: dict[str, object], headers: dict[str, str]):
        captured.append(int(json["template_id"]))
        return httpx.Response(200, json={})

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=fake_client):
        await notify_listmonk.trigger_recovery(
            email="g@example.com", tx_id="tx-1", payload={}, locale="fr-FR"
        )
        await notify_listmonk.trigger_recovery(
            email="g@example.com", tx_id="tx-2", payload={}, locale="fr_FR"
        )
    assert captured == [4, 4]


@pytest.mark.asyncio
async def test_unknown_locale_falls_back_to_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    captured: dict[str, object] = {}

    async def fake_post(url: str, json: dict[str, object], headers: dict[str, str]):
        captured.update(json)
        return httpx.Response(200, json={})

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=fake_client):
        await notify_listmonk.trigger_recovery(
            email="g@example.com", tx_id="tx-1", payload={}, locale="es"
        )
    assert captured["template_id"] == 5  # fallback EN


@pytest.mark.asyncio
async def test_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(return_value=httpx.Response(500, text="boom"))

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            email="x@y", tx_id="tx-1", payload={}
        )
    assert ok is False


@pytest.mark.asyncio
async def test_returns_false_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_listmonk(monkeypatch)
    from app.services import notify_listmonk

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("dns fail"))

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            email="x@y", tx_id="tx-1", payload={}
        )
    assert ok is False
