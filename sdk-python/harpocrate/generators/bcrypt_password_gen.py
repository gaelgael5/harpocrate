"""Générateur de mot de passe bcrypt — type 'bcrypt_password' — LOT_09 SDK.

Génère un mot de passe aléatoire alphanumérique et le hashe en bcrypt.
Retourne un JSON {"plain": "...", "hash": "..."}.

ATTENTION : le JSON retourné contient le mot de passe en clair ("plain").
Documenter clairement que l'utilisateur doit stocker les deux : le hash
pour l'application, le plain uniquement si nécessaire à la configuration initiale.

Note : bcrypt limite les mots de passe à 72 bytes (limitation OpenBSD).
La longueur est limitée à 64 chars dans les descripteurs pour rester en dessous.
"""

from __future__ import annotations

import json
from typing import Any

import bcrypt

from harpocrate.generators.random_gen import generate as random_generate


def generate(descriptor: dict[str, Any]) -> str:
    """Génère un mot de passe et son hash bcrypt.

    Paramètres du descripteur :
        length (int, 12-64, défaut 24) : longueur du mot de passe en clair
        rounds (int, 10-14, défaut 12) : facteur de coût bcrypt

    Retourne :
        JSON str : {"plain": "<mot de passe>", "hash": "<hash bcrypt $2b$...>"}
    """
    length = int(descriptor.get("length", 24))
    rounds = int(descriptor.get("rounds", 12))

    if length < 1:
        raise ValueError(f"length must be >= 1, got {length}")
    if length > 72:
        raise ValueError(f"length must be <= 72 (bcrypt limit), got {length}")
    if rounds < 4 or rounds > 31:
        raise ValueError(f"rounds must be between 4 and 31, got {rounds}")

    plain = random_generate({"length": length, "charset": "alphanum"})
    salt = bcrypt.gensalt(rounds=rounds)
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")

    return json.dumps({"plain": plain, "hash": hashed})
