"""Générateur de bytes aléatoires — type 'bytes' — LOT_09 SDK.

Génère des octets via secrets.token_bytes() puis les encode.
Encodages supportés : base64url (sans padding), hex.
"""

from __future__ import annotations

import base64
import secrets
from typing import Any


def generate(descriptor: dict[str, Any]) -> str:
    """Génère une séquence de bytes aléatoires encodée.

    Paramètres du descripteur :
        length   (int, 1-4096) : nombre de bytes bruts
        encoding (str, 'base64url' ou 'hex', défaut 'base64url')

    Retourne :
        str encodée selon `encoding`
    """
    length = int(descriptor["length"])
    encoding = str(descriptor.get("encoding", "base64url"))

    if length < 1:
        raise ValueError(f"length must be >= 1, got {length}")

    raw = secrets.token_bytes(length)

    if encoding == "base64url":
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    elif encoding == "hex":
        return raw.hex()
    else:
        raise ValueError(f"Unsupported encoding: {encoding!r}. Supported: base64url, hex")
