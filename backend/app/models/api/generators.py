"""Discriminated union des 9 types de descripteurs de génération — LOT_06.

Le serveur VALIDE ces schémas mais n'EXÉCUTE aucune génération.
La génération est effectuée côté client (SDK LOT_09 / UI LOT_11).
"""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Charset nommés admis par le type "random"
_NAMED_CHARSETS = frozenset(
    {"alphanum", "alpha", "numeric", "hex", "base64url", "printable_ascii"}
)

# Printable ASCII : 0x20..0x7E
_PRINTABLE_ASCII_RE = re.compile(r"^[\x20-\x7E]+$")


# ─── random ───────────────────────────────────────────────────────────────────


class RandomDescriptor(BaseModel):
    """Chaîne aléatoire d'un jeu de caractères donné."""

    type: Literal["random"]
    length: int = Field(ge=8, le=1024)
    charset: str = "alphanum"

    @field_validator("charset")
    @classmethod
    def _charset_valid(cls, v: str) -> str:
        if v in _NAMED_CHARSETS:
            return v
        # Charset custom : printable ASCII, longueur ≥ 4
        if not _PRINTABLE_ASCII_RE.match(v):
            raise ValueError(
                "charset custom must contain only printable ASCII characters (0x20-0x7E)"
            )
        if len(v) < 4:
            raise ValueError("custom charset must have at least 4 distinct characters")
        return v


# ─── uuid ─────────────────────────────────────────────────────────────────────


class UuidDescriptor(BaseModel):
    """UUID aléatoire."""

    type: Literal["uuid"]
    version: Literal[4, 7] = 4


# ─── bytes ────────────────────────────────────────────────────────────────────


class BytesDescriptor(BaseModel):
    """Séquence d'octets aléatoires, encodée."""

    type: Literal["bytes"]
    length: int = Field(ge=1, le=4096)
    encoding: Literal["base64url", "hex"] = "base64url"


# ─── passphrase ───────────────────────────────────────────────────────────────


class PassphraseDescriptor(BaseModel):
    """Phrase de passe composée de mots."""

    type: Literal["passphrase"]
    words: int = Field(ge=4, le=16, default=6)
    separator: str = "-"
    language: Literal["en", "fr"] = "en"

    @field_validator("separator")
    @classmethod
    def _separator_valid(cls, v: str) -> str:
        if not v:
            raise ValueError("separator must not be empty")
        if len(v) > 4:
            raise ValueError("separator must not exceed 4 characters")
        if not _PRINTABLE_ASCII_RE.match(v):
            raise ValueError("separator must contain only printable ASCII characters")
        return v


# ─── template ────────────────────────────────────────────────────────────────


class LiteralVariable(BaseModel):
    """Variable littérale dans un template."""

    literal: str


# Forward-ref : les variables récursives pointent vers GenerationDescriptor.
# On les résout à la fin du module avec model_rebuild().
class TemplateDescriptor(BaseModel):
    """Template de chaîne avec variables substituées.

    Récursion limitée à 1 niveau (MVP) : les variables d'un TemplateDescriptor
    ne peuvent elles-mêmes pas être des TemplateDescriptor.
    """

    type: Literal["template"]
    template: str
    variables: dict[str, LiteralVariable | _LeafDescriptor]

    @model_validator(mode="after")
    def _all_placeholders_have_variables(self) -> TemplateDescriptor:
        """Vérifie que chaque {name} dans template a une entrée dans variables."""
        placeholders = set(re.findall(r"\{(\w+)\}", self.template))
        missing = placeholders - self.variables.keys()
        if missing:
            raise ValueError(
                f"Template placeholders without variable definitions: {sorted(missing)}"
            )
        return self


# ─── rsa_keypair ─────────────────────────────────────────────────────────────


class RsaKeypairDescriptor(BaseModel):
    """Paire de clés RSA."""

    type: Literal["rsa_keypair"]
    key_size: Literal[2048, 3072, 4096] = 4096
    format: Literal["pem", "openssh"] = "pem"


# ─── ssh_keypair ─────────────────────────────────────────────────────────────


class SshKeypairDescriptor(BaseModel):
    """Paire de clés SSH."""

    type: Literal["ssh_keypair"]
    algorithm: Literal["ed25519", "rsa"] = "ed25519"


# ─── tls_certificate ─────────────────────────────────────────────────────────


class TlsCertificateDescriptor(BaseModel):
    """Certificat TLS auto-signé."""

    type: Literal["tls_certificate"]
    common_name: str
    subject_alt_names: list[str] = []
    validity_days: int = Field(ge=1, le=3650, default=365)
    key_size: Literal[2048, 4096] = 2048
    self_signed: Literal[True] = True  # MVP : uniquement self-signed

    @field_validator("common_name")
    @classmethod
    def _cn_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("common_name must not be empty")
        return v


# ─── bcrypt_password ─────────────────────────────────────────────────────────


class BcryptPasswordDescriptor(BaseModel):
    """Mot de passe hashé en bcrypt."""

    type: Literal["bcrypt_password"]
    length: int = Field(ge=12, le=64, default=24)
    rounds: int = Field(ge=10, le=14, default=12)


# ─── Union feuille (sans TemplateDescriptor — récursion interdite) ────────────

# _LeafDescriptor est utilisé dans les variables du TemplateDescriptor pour
# interdire la récursion au-delà de 1 niveau.
_LeafDescriptor = Annotated[
    RandomDescriptor
    | UuidDescriptor
    | BytesDescriptor
    | PassphraseDescriptor
    | RsaKeypairDescriptor
    | SshKeypairDescriptor
    | TlsCertificateDescriptor
    | BcryptPasswordDescriptor,
    Field(discriminator="type"),
]


# ─── Union principale ─────────────────────────────────────────────────────────

GenerationDescriptor = Annotated[
    RandomDescriptor
    | UuidDescriptor
    | BytesDescriptor
    | PassphraseDescriptor
    | TemplateDescriptor
    | RsaKeypairDescriptor
    | SshKeypairDescriptor
    | TlsCertificateDescriptor
    | BcryptPasswordDescriptor,
    Field(discriminator="type"),
]

# Résolution des forward-references (TemplateDescriptor utilise _LeafDescriptor)
TemplateDescriptor.model_rebuild()
