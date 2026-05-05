"""Générateur de paire de clés SSH — type 'ssh_keypair' — LOT_09 SDK.

Retourne un JSON {"private": "...", "public": "..."}.

Algorithmes supportés :
  - ed25519 (défaut, recommandé) : clé ED25519 via cryptography
  - rsa : RSA 4096 en format OpenSSH (délègue à rsa_keypair_gen)

Note sécurité : clés générées sans passphrase.
La valeur est chiffrée par AES-GCM par le SDK avant envoi au serveur.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _generate_ed25519() -> str:
    """Génère une paire ED25519 au format OpenSSH."""
    private_key = Ed25519PrivateKey.generate()

    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    return json.dumps(
        {
            "private": priv_bytes.decode("utf-8"),
            "public": pub_bytes.decode("utf-8"),
        }
    )


def _generate_rsa_openssh() -> str:
    """Génère une paire RSA 4096 au format OpenSSH (délègue à rsa_keypair_gen)."""
    from harpocrate.generators.rsa_keypair_gen import generate as rsa_generate

    return rsa_generate({"key_size": 4096, "format": "openssh"})


def generate(descriptor: dict[str, Any]) -> str:
    """Génère une paire de clés SSH.

    Paramètres du descripteur :
        algorithm (str, 'ed25519'|'rsa', défaut 'ed25519')

    Retourne :
        JSON str : {"private": "<OpenSSH private key PEM>", "public": "<OpenSSH public key>"}
    """
    algorithm = str(descriptor.get("algorithm", "ed25519"))

    if algorithm == "ed25519":
        return _generate_ed25519()
    elif algorithm == "rsa":
        return _generate_rsa_openssh()
    else:
        raise ValueError(f"Unsupported SSH algorithm: {algorithm!r}. Supported: ed25519, rsa")
