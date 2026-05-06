"""Chiffrement des credentials de connexions de backup distantes.

Format binaire stocké en BYTEA :
    nonce(12B) || ciphertext || tag(16B)

La clef de chiffrement est dérivée de `HARPOCRATE_HMAC_KEY` via HKDF-SHA256
avec un info distinct pour ne pas réutiliser la HMAC_KEY brute pour de
l'AES-GCM (séparation des usages cryptographiques).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_SIZE = 12  # AES-GCM standard
_KEY_SIZE = 32  # AES-256
_HKDF_INFO = b"harpocrate.remote_backup.credentials.v1"


def _derive_key() -> bytes:
    """Dérive la clef AES-GCM depuis HARPOCRATE_HMAC_KEY via HKDF-SHA256.

    HMAC_KEY est en base64 dans la config. On la décode puis on dérive 32 bytes
    pour AES-256-GCM avec un info dédié (sépare les usages : HMAC vs AES).

    Import lazy de settings : permet aux tests unitaires d'override l'env
    via monkeypatch.setenv avant le 1er appel.
    """
    from app.core.config import settings

    hmac_key_b64 = settings.hmac_key
    hmac_key_bytes = base64.b64decode(hmac_key_b64)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_SIZE,
        salt=None,  # pas de salt — la clef source est déjà uniformément aléatoire
        info=_HKDF_INFO,
    )
    return hkdf.derive(hmac_key_bytes)


def encrypt_credentials(creds: dict[str, Any]) -> bytes:
    """Sérialise `creds` en JSON et chiffre via AES-GCM.

    Retourne les bytes prêts à stocker en BYTEA : nonce || ciphertext || tag.
    """
    plaintext = json.dumps(creds, separators=(",", ":")).encode("utf-8")
    key = _derive_key()
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    # AESGCM.encrypt retourne déjà ciphertext || tag (16 bytes) à la fin.
    return nonce + ciphertext


def decrypt_credentials(blob: bytes) -> dict[str, Any]:
    """Déchiffre un blob produit par `encrypt_credentials`. Retourne le dict original.

    Lève `cryptography.exceptions.InvalidTag` si l'authentification échoue
    (blob altéré, mauvaise clef, etc.).
    """
    if len(blob) < _NONCE_SIZE + 16:
        raise ValueError("Encrypted credentials blob is too short")
    nonce = blob[:_NONCE_SIZE]
    ciphertext_with_tag = blob[_NONCE_SIZE:]
    key = _derive_key()
    plaintext = AESGCM(key).decrypt(nonce, ciphertext_with_tag, associated_data=None)
    return dict(json.loads(plaintext.decode("utf-8")))
