"""Configuration pytest pour les tests SDK Harpocrate."""

from __future__ import annotations

import base64
import os
import uuid

import pytest

# Token de test valide (format correct, HMAC non vérifié côté client)
# Généré avec :
#   version = "1"
#   api_key_id = UUID("12345678-1234-5678-1234-567812345678")
#   exp = 0 (pas d'expiration)
#   perms = 0x3F (toutes les permissions)
#   auth_secret = 32 bytes aléatoires → base64url sans padding (43 chars)
#   dkey = 32 bytes aléatoires → base64url sans padding (43 chars)
#   hmac = 16 bytes aléatoires → base64url sans padding (22 chars)


def _make_b64url(n_bytes: int) -> str:
    """Génère n bytes random encodé base64url sans padding."""
    return base64.urlsafe_b64encode(os.urandom(n_bytes)).rstrip(b"=").decode()


def _uuid_to_b32(uid: uuid.UUID) -> str:
    """Encode un UUID en base32 lowercase 26 chars sans padding."""
    encoded = base64.b32encode(uid.bytes).decode().lower()
    return encoded.rstrip("=")


# Clé de déchiffrement fixe pour les tests
TEST_DKEY_BYTES = bytes(range(32))  # 0x00..0x1F — clé de test
TEST_DKEY_B64 = base64.urlsafe_b64encode(TEST_DKEY_BYTES).rstrip(b"=").decode()

# API key ID de test
TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TEST_ID_B32 = _uuid_to_b32(TEST_API_KEY_ID)

# Auth secret et HMAC de test (format correct, contenu arbitraire)
TEST_AUTH_SECRET = "A" * 43
TEST_HMAC = "B" * 22

# Token de test complet
TEST_TOKEN = f"hrpv_1_{TEST_ID_B32}_0_3f_{TEST_AUTH_SECRET}_{TEST_DKEY_B64}_{TEST_HMAC}"


@pytest.fixture
def test_dkey() -> bytes:
    """Clé de déchiffrement de test (32 bytes)."""
    return TEST_DKEY_BYTES


@pytest.fixture
def test_token() -> str:
    """Token de test hrpv_* valide (HMAC non vérifié côté client)."""
    return TEST_TOKEN
