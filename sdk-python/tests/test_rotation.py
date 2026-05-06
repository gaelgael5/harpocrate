"""Tests RotationRegistry + intégration VaultClient (LOT_22)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harpocrate.exceptions import SecretRefreshFailed
from harpocrate.rotation import RotationRegistry

# ─── RotationRegistry pure tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_fires_specific_callbacks_in_order() -> None:
    reg = RotationRegistry()
    calls: list[tuple[str, str]] = []

    def cb1(value: str) -> None:
        calls.append(("cb1", value))

    def cb2(value: str) -> None:
        calls.append(("cb2", value))

    reg.register_specific("k", cb1)
    reg.register_specific("k", cb2)

    await reg.fire("k", "new-value")

    # Ordre d'enregistrement préservé
    assert calls == [("cb1", "new-value"), ("cb2", "new-value")]


@pytest.mark.asyncio
async def test_registry_fires_global_after_specific() -> None:
    reg = RotationRegistry()
    order: list[str] = []

    reg.register_specific("k", lambda v: order.append(f"specific:{v}"))
    reg.register_global(lambda name, v: order.append(f"global:{name}:{v}"))

    await reg.fire("k", "x")
    assert order == ["specific:x", "global:k:x"]


@pytest.mark.asyncio
async def test_registry_supports_async_callbacks() -> None:
    reg = RotationRegistry()
    captured: list[str] = []

    async def async_cb(value: str) -> None:
        captured.append(f"async:{value}")

    reg.register_specific("k", async_cb)
    await reg.fire("k", "v")
    assert captured == ["async:v"]


@pytest.mark.asyncio
async def test_registry_does_not_break_on_callback_exception() -> None:
    """Une exception dans un callback ne bloque pas les suivants."""
    reg = RotationRegistry()
    seen: list[str] = []

    def boom(value: str) -> None:
        raise RuntimeError("boom")

    reg.register_specific("k", boom)
    reg.register_specific("k", lambda v: seen.append(v))

    await reg.fire("k", "v")
    assert seen == ["v"]


@pytest.mark.asyncio
async def test_registry_only_fires_for_matching_secret_name() -> None:
    reg = RotationRegistry()
    seen: list[str] = []

    reg.register_specific("anthropic_api_key", lambda v: seen.append(f"a:{v}"))
    reg.register_specific("openai_api_key", lambda v: seen.append(f"o:{v}"))

    await reg.fire("anthropic_api_key", "new")
    assert seen == ["a:new"]


def test_registry_clear() -> None:
    reg = RotationRegistry()
    reg.register_specific("k", lambda v: None)
    reg.register_global(lambda n, v: None)
    reg.clear()
    assert reg._specific == {}
    assert reg._global == []


# ─── VaultClient integration tests ────────────────────────────────────────────


def _make_fake_client() -> Any:
    """Construit un VaultClient avec HTTP/secrets mockés."""
    from harpocrate.client import VaultClient

    # On bypass tout l'init en patchant les méthodes coûteuses
    with (
        patch("harpocrate.client.parse_token") as parse,
        patch("harpocrate.client.VaultHttpClient") as http_cls,
    ):
        parse.return_value = MagicMock(
            api_key_id="key-id",
            decryption_key=b"k" * 32,
            permissions=[],
            exp=None,
        )
        http = MagicMock()
        http.get = MagicMock(
            return_value={"wallet_id": "11111111-1111-1111-1111-111111111111"}
        )
        http_cls.return_value = http
        client = VaultClient(token="hrpv_x", base_url="http://t")
        return client


@pytest.mark.asyncio
async def test_notify_auth_error_calls_get_with_force_refresh_and_fires_callback() -> None:
    client = _make_fake_client()
    captured: list[str] = []

    @client.on_auth_error("anthropic_api_key")
    def handler(value: str) -> None:
        captured.append(value)

    # Mock secrets.get pour retourner une "nouvelle valeur"
    client.secrets.get = MagicMock(return_value="new-rotated-key")

    new_value = await client.notify_auth_error("anthropic_api_key")
    assert new_value == "new-rotated-key"
    assert captured == ["new-rotated-key"]
    client.secrets.get.assert_called_once_with(
        "anthropic_api_key", force_refresh=True
    )


@pytest.mark.asyncio
async def test_notify_auth_error_raises_if_refresh_fails() -> None:
    client = _make_fake_client()
    client.secrets.get = MagicMock(side_effect=RuntimeError("revoked"))

    with pytest.raises(SecretRefreshFailed) as exc_info:
        await client.notify_auth_error("k")
    assert "revoked" in str(exc_info.value)
    assert exc_info.value.secret_name == "k"


@pytest.mark.asyncio
async def test_on_any_auth_error_called_for_all_secrets() -> None:
    client = _make_fake_client()
    seen: list[tuple[str, str]] = []

    @client.on_any_auth_error
    async def global_cb(secret: str, value: str) -> None:
        seen.append((secret, value))

    client.secrets.get = MagicMock(side_effect=["v1", "v2"])
    await client.notify_auth_error("a")
    await client.notify_auth_error("b")
    assert seen == [("a", "v1"), ("b", "v2")]


@pytest.mark.asyncio
async def test_using_secret_context_manager() -> None:
    client = _make_fake_client()
    client.secrets.get = MagicMock(return_value="cached-value")

    async with client.using_secret("k") as get_value:
        v = await get_value()
    assert v == "cached-value"


@pytest.mark.asyncio
async def test_using_secret_retry_calls_notify_auth_error() -> None:
    client = _make_fake_client()
    seen: list[str] = []

    @client.on_auth_error("k")
    def cb(value: str) -> None:
        seen.append(value)

    client.secrets.get = MagicMock(return_value="rotated-value")
    async with client.using_secret("k") as get_value:
        v = await get_value(retry=True)
    assert v == "rotated-value"
    assert seen == ["rotated-value"]
