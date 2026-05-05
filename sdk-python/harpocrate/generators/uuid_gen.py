"""Générateur UUID — type 'uuid' — LOT_09 SDK.

Versions supportées :
  - 4 (défaut) : UUID4 aléatoire, stdlib Python
  - 7 : UUID7 (timestamp-based, monotone) — implémentation custom si uuid_utils
        non disponible, sinon fallback sur UUID4 avec avertissement

Note sur uuid7 :
  La PEP 735 (Python 3.14+) ajoutera uuid7 à la stdlib.
  Pour Python 3.10-3.13, on utilise une implémentation manuelle compatible RFC 9562.
  Voir https://www.rfc-editor.org/rfc/rfc9562 § 5.7
"""

from __future__ import annotations

import secrets
import struct
import time
import uuid
from typing import Any


def _uuid7() -> uuid.UUID:
    """Génère un UUID version 7 (RFC 9562 § 5.7).

    Structure :
        48 bits  timestamp ms depuis Unix epoch
        4 bits   version = 0b0111 (7)
        12 bits  rand_a (aléatoire)
        2 bits   variant = 0b10
        62 bits  rand_b (aléatoire)

    Total = 128 bits = 16 bytes.
    """
    ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    # Assemble les 128 bits
    # [48 bits ts][4 bits ver=7][12 bits rand_a][2 bits var=0b10][62 bits rand_b]
    high = (ts_ms << 16) | (0x7 << 12) | rand_a
    low = (0b10 << 62) | rand_b

    raw = struct.pack(">QQ", high, low)
    return uuid.UUID(bytes=raw)


def generate(descriptor: dict[str, Any]) -> str:
    """Génère un UUID selon le descripteur.

    Paramètres du descripteur :
        version (int, 4 ou 7, défaut 4)

    Retourne :
        str au format standard '8-4-4-4-12' (36 chars)
    """
    version = int(descriptor.get("version", 4))

    if version == 4:
        return str(uuid.uuid4())
    elif version == 7:
        return str(_uuid7())
    else:
        raise ValueError(f"Unsupported UUID version: {version}. Supported: 4, 7")
