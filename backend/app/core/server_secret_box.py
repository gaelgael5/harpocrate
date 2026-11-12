"""Chiffrement au repos des secrets SERVEUR rangés en base (ex. token Listmonk).

Ne concerne pas les secrets des utilisateurs : ceux-là ne sont jamais déchiffrés par le
serveur. Un secret serveur, lui, doit être relu par le serveur pour appeler un service
tiers — il est seulement protégé contre la lecture directe de la base ou d'un backup.

Format BYTEA : nonce(12B) || ciphertext || tag(16B), AES-256-GCM. Clé dérivée de
`HARPOCRATE_HMAC_KEY` par HKDF-SHA256 avec un `purpose` distinct par usage : deux usages
ne partagent jamais la même clé. Même procédé que `services/remote_backup_crypto.py`
(identifiants des backups distants), qui garde son propre `info` historique.

Conséquence assumée : changer ou perdre `HARPOCRATE_HMAC_KEY` rend ces secrets
illisibles ; il faut les ressaisir.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_SIZE = 12
_TAG_SIZE = 16
_KEY_SIZE = 32


def _derive_key(purpose: bytes) -> bytes:
    # Import différé : les tests posent l'environnement avant le premier appel.
    from app.core.config import settings

    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_SIZE,
        salt=None,  # la clé source est déjà uniformément aléatoire
        info=purpose,
    ).derive(base64.b64decode(settings.hmac_key))


def seal(plaintext: str, *, purpose: bytes) -> bytes:
    nonce = os.urandom(_NONCE_SIZE)
    return nonce + AESGCM(_derive_key(purpose)).encrypt(nonce, plaintext.encode("utf-8"), None)


def unseal(blob: bytes, *, purpose: bytes) -> str:
    """Lève `cryptography.exceptions.InvalidTag` si le blob est altéré ou si la clé a
    changé (HMAC_KEY différente, autre `purpose`)."""
    if len(blob) < _NONCE_SIZE + _TAG_SIZE:
        raise ValueError("sealed blob is too short")
    nonce, ciphertext = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
    return AESGCM(_derive_key(purpose)).decrypt(nonce, ciphertext, None).decode("utf-8")
