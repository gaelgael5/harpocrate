"""Tests du client listmonk (LOT_57)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import SecretStr

from app.models.db.listmonk_connection import ListmonkConnection


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _connection() -> ListmonkConnection:
    """Connexion résolue en base par l'appelant (feature 3) : le client ne lit plus
    aucune variable d'environnement."""
    return ListmonkConnection(
        url="http://listmonk.test:9000",
        api_user="harpocrate-api",
        token=SecretStr("secret-token"),
    )


def _make_two_step_mock_client(
    *, subscriber_response: httpx.Response, tx_response: httpx.Response
) -> tuple[AsyncMock, list[dict[str, object]]]:
    """Mock httpx.AsyncClient qui répond séquentiellement à 2 POST :
    d'abord `/api/subscribers` (upsert), puis `/api/tx` (trigger).
    Retourne le mock + la liste des appels capturés.
    """
    captured_calls: list[dict[str, object]] = []
    responses = iter([subscriber_response, tx_response])

    async def fake_post(url: str, json: dict[str, object], headers: dict[str, str]):
        captured_calls.append({"url": url, "json": json, "headers": headers})
        return next(responses)

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=fake_post)
    return fake_client, captured_calls


@pytest.mark.asyncio
async def test_posts_correct_body_and_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import notify_listmonk

    fake_client, calls = _make_two_step_mock_client(
        subscriber_response=httpx.Response(200, json={"data": {}}),
        tx_response=httpx.Response(200, json={"data": {}}),
    )

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            connection=_connection(),
            email="g@example.com",
            tx_id="tx-abc",
            payload={"recoveryLink": "https://x/r/abc", "expiresInMinutes": "30"},
            template_id=7,
        )
    assert ok is True
    assert len(calls) == 2

    # Premier call : upsert subscriber
    sub_call = calls[0]
    assert sub_call["url"] == "http://listmonk.test:9000/api/subscribers"
    sub_body = sub_call["json"]
    assert sub_body["email"] == "g@example.com"
    assert sub_body["status"] == "enabled"
    assert sub_body["preconfirm_subscriptions"] is True

    # Deuxième call : trigger transactional
    tx_call = calls[1]
    assert tx_call["url"] == "http://listmonk.test:9000/api/tx"
    tx_body = tx_call["json"]
    assert tx_body == {
        "subscriber_email": "g@example.com",
        "template_id": 7,
        "data": {"recoveryLink": "https://x/r/abc", "expiresInMinutes": "30"},
        "headers": [{"X-Harpocrate-Tx-Id": "tx-abc"}],
    }
    assert tx_call["headers"]["Authorization"] == "token harpocrate-api:secret-token"


@pytest.mark.asyncio
async def test_subscriber_409_already_exists_is_treated_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """409 sur /api/subscribers = subscriber déjà présent → on continue."""
    from app.services import notify_listmonk

    fake_client, _ = _make_two_step_mock_client(
        subscriber_response=httpx.Response(409, json={"message": "exists"}),
        tx_response=httpx.Response(200, json={"data": {}}),
    )

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            connection=_connection(), email="g@example.com", tx_id="tx-1", payload={}, template_id=7
        )
    assert ok is True


@pytest.mark.asyncio
async def test_aborts_when_subscriber_create_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si /api/subscribers échoue (5xx), on n'appelle pas /api/tx."""
    from app.services import notify_listmonk

    fake_client, calls = _make_two_step_mock_client(
        subscriber_response=httpx.Response(500, text="boom"),
        tx_response=httpx.Response(200, json={"data": {}}),
    )

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            connection=_connection(), email="g@example.com", tx_id="tx-1", payload={}, template_id=7
        )
    assert ok is False
    # Un seul call (subscribers), pas de tx
    assert len(calls) == 1
    assert "subscribers" in str(calls[0]["url"])


@pytest.mark.asyncio
async def test_trigger_recovery_sends_given_template_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le template_id reçu de l'appelant part tel quel : aucune sélection par
    locale ici, elle se fait en base (`listmonk_templates.db_resolve`)."""
    from app.services import notify_listmonk

    fake_client, calls = _make_two_step_mock_client(
        subscriber_response=httpx.Response(200, json={}),
        tx_response=httpx.Response(200, json={}),
    )

    with patch("httpx.AsyncClient", return_value=fake_client):
        await notify_listmonk.trigger_recovery(
            connection=_connection(),
            email="g@example.com",
            tx_id="tx-1",
            payload={},
            template_id=42,
        )
    assert calls[1]["json"]["template_id"] == 42


@pytest.mark.asyncio
async def test_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import notify_listmonk

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(return_value=httpx.Response(500, text="boom"))

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            connection=_connection(), email="x@y", tx_id="tx-1", payload={}, template_id=7
        )
    assert ok is False


@pytest.mark.asyncio
async def test_returns_false_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import notify_listmonk

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("dns fail"))

    with patch("httpx.AsyncClient", return_value=fake_client):
        ok = await notify_listmonk.trigger_recovery(
            connection=_connection(), email="x@y", tx_id="tx-1", payload={}, template_id=7
        )
    assert ok is False
