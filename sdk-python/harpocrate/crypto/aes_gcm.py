"""AES-256-GCM encrypt/decrypt — format nonce(12) || ciphertext+tag(16) — LOT_09 SDK.

Convention blob : nonce(12 bytes) || ciphertext || tag(16 bytes)
  - Le tag est inclus dans ciphertext_with_tag par la lib cryptography.
  - Le blob total fait au minimum 12 + 16 = 28 bytes.

Sécurité :
  - Nonce généré via os.urandom(12) → 96 bits, compatible GCM standard.
  - Tag de 128 bits (défaut de AESGCM).
  - La clé doit faire exactement 32 bytes (AES-256).
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from harpocrate.exceptions import VaultDecryptionError

_NONCE_LEN = 12
_TAG_LEN = 16
_MIN_BLOB_LEN = _NONCE_LEN + _TAG_LEN


def aes_gcm_encrypt(plaintext: bytes, key: bytes, aad: bytes = b"") -> bytes:
    """Chiffre ``plaintext`` avec AES-256-GCM.

    Paramètres :
        plaintext : données à chiffrer.
        key : clé AES-256 de 32 bytes.
        aad : Additional Authenticated Data (optionnel, non chiffré mais authentifié).

    Retourne :
        blob = nonce(12) || ciphertext || tag(16)
    """
    if len(key) != 32:
        raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, aad or None)
    return nonce + ciphertext_with_tag


def aes_gcm_decrypt(blob: bytes, key: bytes, aad: bytes = b"") -> bytes:
    """Déchiffre un blob AES-256-GCM.

    Paramètres :
        blob : nonce(12) || ciphertext || tag(16), au minimum 28 bytes.
        key : clé AES-256 de 32 bytes.
        aad : Additional Authenticated Data utilisée lors du chiffrement.

    Retourne :
        plaintext

    Lève :
        VaultDecryptionError si le tag est invalide (mauvaise clé ou blob corrompu).
        ValueError si le blob est trop court ou la clé invalide.
    """
    if len(key) != 32:
        raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")
    if len(blob) < _MIN_BLOB_LEN:
        raise ValueError(
            f"Blob too short: expected at least {_MIN_BLOB_LEN} bytes, got {len(blob)}"
        )
    nonce = blob[:_NONCE_LEN]
    ciphertext_with_tag = blob[_NONCE_LEN:]
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext_with_tag, aad or None)
    except Exception as exc:
        raise VaultDecryptionError("AES-GCM decryption failed: invalid tag or wrong key") from exc
