"""Tests du chiffrement des credentials remote backup."""

from __future__ import annotations

import base64

import pytest
from cryptography.exceptions import InvalidTag

from app.services import remote_backup_crypto as rbc


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force HARPOCRATE_HMAC_KEY à une valeur de test fixée."""
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")

    # Recharger settings (pattern setattr propre) et le module crypto pour
    # qu'il relise l'env. Pas de réassignation globale de settings
    # (cf. test_admin_remote_backups.py:env).
    import app.core.config

    _new_s = app.core.config.Settings()
    for _a, _v in _new_s.model_dump().items():
        monkeypatch.setattr(app.core.config.settings, _a, _v)
    import importlib

    importlib.reload(rbc)


def test_round_trip_simple_dict() -> None:
    creds = {"username": "alice", "password": "s3cret!"}
    blob = rbc.encrypt_credentials(creds)
    assert isinstance(blob, bytes)
    assert blob != creds["password"].encode()  # smoke check : bien chiffré
    decoded = rbc.decrypt_credentials(blob)
    assert decoded == creds


def test_round_trip_nested_dict() -> None:
    creds = {
        "username": "bob",
        "auth_method": "private_key",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nABCDEF\n-----END RSA PRIVATE KEY-----",
        "private_key_passphrase": "phrase",
    }
    blob = rbc.encrypt_credentials(creds)
    decoded = rbc.decrypt_credentials(blob)
    assert decoded == creds


def test_two_encryptions_differ_due_to_random_nonce() -> None:
    """Deux chiffrements du même payload doivent différer (nonce aléatoire)."""
    creds = {"u": "x", "p": "y"}
    blob_a = rbc.encrypt_credentials(creds)
    blob_b = rbc.encrypt_credentials(creds)
    assert blob_a != blob_b
    assert rbc.decrypt_credentials(blob_a) == rbc.decrypt_credentials(blob_b) == creds


def test_tampered_blob_raises_invalid_tag() -> None:
    blob = rbc.encrypt_credentials({"u": "x"})
    tampered = bytearray(blob)
    tampered[-1] ^= 0xFF  # flip un bit du tag
    with pytest.raises(InvalidTag):
        rbc.decrypt_credentials(bytes(tampered))


def test_blob_too_short_raises_value_error() -> None:
    with pytest.raises(ValueError):
        rbc.decrypt_credentials(b"too short")


def test_credentials_are_not_present_verbatim_in_blob() -> None:
    """Aucune valeur de credential ne doit apparaître en clair dans le blob."""
    creds = {"username": "myuser_xyz", "password": "MyP@ssw0rd"}
    blob = rbc.encrypt_credentials(creds)
    assert b"myuser_xyz" not in blob
    assert b"MyP@ssw0rd" not in blob
