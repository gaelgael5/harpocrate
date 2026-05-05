"""Générateur de certificat TLS auto-signé — type 'tls_certificate' — LOT_09 SDK.

AVERTISSEMENT : les certificats générés sont auto-signés uniquement.
Ils n'ont PAS de chaîne de confiance reconnue par les navigateurs ou systèmes.
Ils peuvent être utilisés pour du chiffrement interne (entre services),
mais ne doivent pas être présentés à des clients publics.

Retourne un JSON {"certificate": "<PEM cert>", "private_key": "<PEM key>"}.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate(descriptor: dict[str, Any]) -> str:
    """Génère un certificat TLS auto-signé.

    Paramètres du descripteur :
        common_name       (str) : CN du certificat (ex: "example.com")
        subject_alt_names (list[str], défaut []) : SANs DNS ou IP
        validity_days     (int, 1-3650, défaut 365) : durée de validité
        key_size          (int, 2048|4096, défaut 2048)
        self_signed       (bool, toujours True) : MVP uniquement

    Retourne :
        JSON str : {"certificate": "<PEM>", "private_key": "<PEM>"}
    """
    common_name = str(descriptor["common_name"]).strip()
    if not common_name:
        raise ValueError("common_name must not be empty")

    san_names_raw = descriptor.get("subject_alt_names", [])
    if not isinstance(san_names_raw, list):
        raise ValueError("subject_alt_names must be a list")
    san_names: list[str] = [str(s) for s in san_names_raw]

    validity_days = int(descriptor.get("validity_days", 365))
    key_size_raw = int(descriptor.get("key_size", 2048))

    if key_size_raw not in (2048, 4096):
        raise ValueError(f"Unsupported key_size: {key_size_raw}. Supported: 2048, 4096")

    # Génération de la clé privée
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size_raw,
    )

    # Sujet et émetteur identiques (auto-signé)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    # Construction des SANs
    san_list: list[x509.GeneralName] = []
    for san in san_names:
        try:
            # Tente d'abord de parser comme IP
            ip = ipaddress.ip_address(san)
            san_list.append(x509.IPAddress(ip))
        except ValueError:
            san_list.append(x509.DNSName(san))

    now = datetime.datetime.now(datetime.timezone.utc)
    not_before = now
    not_after = now + datetime.timedelta(days=validity_days)

    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
    )

    if san_list:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )

    # Extension Basic Constraints : pas une CA
    builder = builder.add_extension(
        x509.BasicConstraints(ca=False, path_length=None),
        critical=True,
    )

    cert = builder.sign(private_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    return json.dumps({"certificate": cert_pem, "private_key": key_pem})
