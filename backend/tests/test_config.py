"""Tests pour app.core.config — validation des floors KDF/RSA/HMAC."""
from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from pydantic import ValidationError


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Variables d'env minimales pour instancier Settings."""
    hmac_key = base64.b64encode(b"x" * 32).decode()
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "harpocrate-vault")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", hmac_key)
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://test.local")
    yield


def test_settings_loads_with_minimal_env(base_env: None) -> None:
    from app.core.config import Settings

    s = Settings()
    assert s.kdf_memory_kb == 65536
    assert s.kdf_iterations == 3
    assert s.kdf_parallelism == 4
    assert s.rsa_key_size_min == 2048
    assert s.passphrase_length_min == 12


def test_settings_rejects_low_kdf_memory(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_KDF_MEMORY_KB", "10000")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_low_kdf_iterations(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_KDF_ITERATIONS", "1")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_low_kdf_parallelism(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_KDF_PARALLELISM", "1")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_invalid_hmac_format(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", "not-base64-!!!")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_short_hmac_key(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    short = base64.b64encode(b"x" * 16).decode()
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", short)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_wrong_rsa_size(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_RSA_KEY_SIZE_MIN", "1024")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_accepts_rsa_4096(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_RSA_KEY_SIZE_MIN", "4096")
    s = Settings()
    assert s.rsa_key_size_min == 4096
