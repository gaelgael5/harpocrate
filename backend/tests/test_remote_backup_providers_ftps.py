"""Tests FtpsProvider — validation des inputs (LOT_55).

Tests réseau réel hors scope. On valide les guards d'init.
"""
from __future__ import annotations

import base64

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_init_requires_host() -> None:
    from app.services.remote_backup_providers.ftps import FtpsProvider
    with pytest.raises(ValueError, match="host"):
        FtpsProvider(
            config={},
            credentials={"username": "u", "password": "p"},
        )


def test_init_requires_username() -> None:
    from app.services.remote_backup_providers.ftps import FtpsProvider
    with pytest.raises(ValueError, match="username"):
        FtpsProvider(
            config={"host": "h"},
            credentials={"password": "p"},
        )


def test_init_requires_password() -> None:
    from app.services.remote_backup_providers.ftps import FtpsProvider
    with pytest.raises(ValueError, match="password"):
        FtpsProvider(
            config={"host": "h"},
            credentials={"username": "u"},
        )


def test_init_invalid_port_type() -> None:
    from app.services.remote_backup_providers.ftps import FtpsProvider
    with pytest.raises(ValueError, match="port"):
        FtpsProvider(
            config={"host": "h", "port": "not-a-number"},
            credentials={"username": "u", "password": "p"},
        )


def test_init_accepts_valid_config() -> None:
    from app.services.remote_backup_providers.ftps import FtpsProvider
    p = FtpsProvider(
        config={"host": "ftp.test", "port": 990, "use_tls": True},
        credentials={"username": "u", "password": "p"},
    )
    assert p._host == "ftp.test"
    assert p._port == 990
    assert p._use_tls is True


def test_normalize_path_defaults_to_dot() -> None:
    from app.services.remote_backup_providers.ftps import FtpsProvider
    assert FtpsProvider._normalize_path("") == "."
    assert FtpsProvider._normalize_path("   ") == "."
    assert FtpsProvider._normalize_path("/foo") == "/foo"


def test_factory_creates_correct_provider() -> None:
    from app.services.remote_backup_providers import (
        FtpsProvider,
        S3CompatibleProvider,
        get_provider,
    )

    s3 = get_provider(
        "s3",
        {"bucket": "b", "region": "r"},
        {"access_key_id": "k", "secret_access_key": "s"},
    )
    assert isinstance(s3, S3CompatibleProvider)

    ftps = get_provider(
        "ftps",
        {"host": "h"},
        {"username": "u", "password": "p"},
    )
    assert isinstance(ftps, FtpsProvider)


def test_factory_rejects_unknown_kind() -> None:
    from app.services.remote_backup_providers import get_provider
    with pytest.raises(ValueError, match="Unsupported"):
        get_provider("azure-blob", {}, {})
