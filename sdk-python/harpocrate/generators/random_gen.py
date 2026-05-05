"""Générateur de chaîne aléatoire — type 'random' — LOT_09 SDK.

Utilise secrets.choice() (pas random.*) pour la sécurité cryptographique.
Jeux de caractères nommés pris en charge :
  - alphanum   : a-zA-Z0-9
  - alpha      : a-zA-Z
  - numeric    : 0-9
  - hex        : 0-9a-f
  - base64url  : a-zA-Z0-9-_
  - printable_ascii : 0x20..0x7E (espace inclus)
  - <custom>   : chaîne littérale printable ASCII (longueur >= 4)
"""

from __future__ import annotations

import secrets
import string
from typing import Any

from harpocrate.exceptions import GeneratorError

_CHARSETS: dict[str, str] = {
    "alphanum": string.ascii_letters + string.digits,
    "alpha": string.ascii_letters,
    "numeric": string.digits,
    "hex": string.hexdigits[:16],  # 0-9a-f lowercase
    "base64url": string.ascii_letters + string.digits + "-_",
    "printable_ascii": "".join(chr(c) for c in range(0x20, 0x7F)),
}


def _resolve_charset(charset: str) -> str:
    """Retourne le jeu de caractères effectif.

    Lève GeneratorError si le jeu est invalide.
    """
    if charset in _CHARSETS:
        return _CHARSETS[charset]
    # Charset personnalisé
    if len(charset) < 4:
        raise GeneratorError(f"Custom charset must have at least 4 characters, got {len(charset)}")
    return charset


def generate(descriptor: dict[str, Any]) -> str:
    """Génère une chaîne aléatoire selon le descripteur.

    Paramètres du descripteur :
        length  (int, 8-1024) : longueur de la chaîne
        charset (str, défaut 'alphanum') : jeu de caractères ou custom

    Retourne :
        str de longueur `length`
    """
    length = int(descriptor["length"])
    charset_name = str(descriptor.get("charset", "alphanum"))

    if length < 1:
        raise GeneratorError(f"length must be >= 1, got {length}")

    charset = _resolve_charset(charset_name)
    return "".join(secrets.choice(charset) for _ in range(length))
