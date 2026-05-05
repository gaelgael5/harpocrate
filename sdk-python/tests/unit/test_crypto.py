"""Tests de l'implémentation AES-256-GCM — LOT_09."""

from __future__ import annotations

import os

import pytest

from harpocrate.crypto.aes_gcm import aes_gcm_decrypt, aes_gcm_encrypt
from harpocrate.exceptions import VaultDecryptionError


class TestAesGcmEncrypt:
    """Tests du chiffrement AES-256-GCM."""

    def test_encrypt_returns_bytes(self) -> None:
        """encrypt() retourne des bytes."""
        key = os.urandom(32)
        blob = aes_gcm_encrypt(b"hello", key)
        assert isinstance(blob, bytes)

    def test_blob_length_minimum(self) -> None:
        """Le blob fait au minimum nonce(12) + tag(16) = 28 bytes."""
        key = os.urandom(32)
        blob = aes_gcm_encrypt(b"", key)
        assert len(blob) >= 28

    def test_blob_length_with_plaintext(self) -> None:
        """La longueur du blob est 12 + len(plaintext) + 16."""
        key = os.urandom(32)
        plaintext = b"hello world"
        blob = aes_gcm_encrypt(plaintext, key)
        assert len(blob) == 12 + len(plaintext) + 16

    def test_two_encrypts_differ(self) -> None:
        """Deux chiffrements du même message donnent des blobs différents (nonce aléatoire)."""
        key = os.urandom(32)
        plaintext = b"secret value"
        blob1 = aes_gcm_encrypt(plaintext, key)
        blob2 = aes_gcm_encrypt(plaintext, key)
        assert blob1 != blob2  # nonces différents

    def test_invalid_key_length(self) -> None:
        """Une clé de mauvaise longueur lève ValueError."""
        with pytest.raises(ValueError, match="32 bytes"):
            aes_gcm_encrypt(b"hello", b"short_key")


class TestAesGcmDecrypt:
    """Tests du déchiffrement AES-256-GCM."""

    def test_decrypt_known_vector(self) -> None:
        """Round-trip : ce qu'on chiffre peut être déchiffré."""
        key = bytes(range(32))  # clé fixe pour reproductibilité
        plaintext = b"test plaintext known vector"
        blob = aes_gcm_encrypt(plaintext, key)
        recovered = aes_gcm_decrypt(blob, key)
        assert recovered == plaintext

    def test_decrypt_empty_plaintext(self) -> None:
        """On peut chiffrer et déchiffrer des données vides."""
        key = os.urandom(32)
        blob = aes_gcm_encrypt(b"", key)
        assert aes_gcm_decrypt(blob, key) == b""

    def test_decrypt_large_payload(self) -> None:
        """Le déchiffrement fonctionne sur des payloads larges."""
        key = os.urandom(32)
        plaintext = os.urandom(10_000)
        blob = aes_gcm_encrypt(plaintext, key)
        assert aes_gcm_decrypt(blob, key) == plaintext

    def test_wrong_key_raises_decryption_error(self) -> None:
        """Une clé incorrecte lève VaultDecryptionError (tag invalide)."""
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        blob = aes_gcm_encrypt(b"secret", key1)
        with pytest.raises(VaultDecryptionError):
            aes_gcm_decrypt(blob, key2)

    def test_corrupted_blob_raises_decryption_error(self) -> None:
        """Un blob corrompu lève VaultDecryptionError."""
        key = os.urandom(32)
        blob = bytearray(aes_gcm_encrypt(b"secret", key))
        blob[-1] ^= 0xFF  # corrompt le dernier byte du tag
        with pytest.raises(VaultDecryptionError):
            aes_gcm_decrypt(bytes(blob), key)

    def test_blob_too_short_raises_value_error(self) -> None:
        """Un blob trop court (< 28 bytes) lève ValueError."""
        key = os.urandom(32)
        with pytest.raises(ValueError, match="too short"):
            aes_gcm_decrypt(b"tooshort", key)

    def test_with_aad(self) -> None:
        """Les AAD sont correctement vérifiées lors du déchiffrement."""
        key = os.urandom(32)
        plaintext = b"authenticated data test"
        aad = b"wallet-id:abc123"
        blob = aes_gcm_encrypt(plaintext, key, aad=aad)
        # Déchiffrement avec AAD correctes → succès
        assert aes_gcm_decrypt(blob, key, aad=aad) == plaintext

    def test_wrong_aad_raises_decryption_error(self) -> None:
        """Des AAD incorrectes lors du déchiffrement lèvent VaultDecryptionError."""
        key = os.urandom(32)
        plaintext = b"authenticated data test"
        blob = aes_gcm_encrypt(plaintext, key, aad=b"correct-aad")
        with pytest.raises(VaultDecryptionError):
            aes_gcm_decrypt(blob, key, aad=b"wrong-aad")

    def test_invalid_key_length(self) -> None:
        """Une clé de mauvaise longueur lève ValueError."""
        blob = b"\x00" * 28
        with pytest.raises(ValueError, match="32 bytes"):
            aes_gcm_decrypt(blob, b"short")
