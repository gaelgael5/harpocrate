"""Tests génération paire AGE (LOT_56)."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


_VALID_OUTPUT = (
    b"# created: 2026-05-06T12:00:00Z\n"
    b"# public key: age1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqsx\n"
    b"AGE-SECRET-KEY-1QYQSZQGPQYQSZQGPQYQSZQGPQYQSZQGPQYQSZQGPQYQSZQGPQYQSXAB\n"
)


@pytest.mark.asyncio
async def test_generate_age_keypair_parses_age_keygen_output() -> None:
    from app.services.age_keygen import generate_age_keypair

    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(_VALID_OUTPUT, b""))

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    ):
        public_key, private_key = await generate_age_keypair()

    assert public_key.startswith("age1qyqsz")
    assert private_key.startswith("AGE-SECRET-KEY-1")


@pytest.mark.asyncio
async def test_generate_age_keypair_raises_on_nonzero_exit() -> None:
    from app.services.age_keygen import AgeKeygenError, generate_age_keypair

    fake_proc = AsyncMock()
    fake_proc.returncode = 1
    fake_proc.communicate = AsyncMock(return_value=(b"", b"some error"))

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    ), pytest.raises(AgeKeygenError, match="exited with code 1"):
        await generate_age_keypair()


@pytest.mark.asyncio
async def test_generate_age_keypair_raises_on_unparseable_output() -> None:
    from app.services.age_keygen import AgeKeygenError, generate_age_keypair

    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"garbage output", b""))

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    ), pytest.raises(AgeKeygenError, match="could not parse"):
        await generate_age_keypair()
