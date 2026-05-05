"""Générateur de paire de clés RSA — type 'rsa_keypair' — LOT_09 SDK.

Retourne un JSON {"private": "...", "public": "..."}.

Tailles supportées : 2048, 3072, 4096 (défaut 4096).
Formats : 'pem' (PKCS8/SubjectPublicKeyInfo) ou 'openssh'.

Note sécurité : clés générées sans passphrase (NoEncryption).
La valeur est chiffrée par AES-GCM par le SDK avant envoi au serveur.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate(descriptor: dict[str, Any]) -> str:
    """Génère une paire de clés RSA.

    Paramètres du descripteur :
        key_size (int, 2048|3072|4096, défaut 4096)
        format   (str, 'pem'|'openssh', défaut 'pem')

    Retourne :
        JSON str : {"private": "<PEM ou OpenSSH>", "public": "<PEM ou OpenSSH>"}
    """
    key_size = int(descriptor.get("key_size", 4096))
    fmt = str(descriptor.get("format", "pem"))

    if key_size not in (2048, 3072, 4096):
        raise ValueError(f"Unsupported RSA key_size: {key_size}. Supported: 2048, 3072, 4096")

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
    )

    if fmt == "pem":
        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    elif fmt == "openssh":
        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
    else:
        raise ValueError(f"Unsupported RSA key format: {fmt!r}. Supported: pem, openssh")

    return json.dumps(
        {
            "private": priv_bytes.decode("utf-8"),
            "public": pub_bytes.decode("utf-8"),
        }
    )
