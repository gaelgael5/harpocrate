"""Parsing du token hrpv_* côté client — LOT_09 SDK.

Format : hrpv_{v}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64url}_{dkey_b64url}_{hmac_b64url}

Le client :
  - Parse les champs pour en extraire wallet_id, decryption_key, permissions
  - Ne vérifie PAS le HMAC (la clé HMAC_KEY n'est pas côté client)
  - Vérifie l'expiration localement si exp != 0

Longueurs fixes (même convention que le backend) :
  - id_b32 : 26 chars (UUID 16 bytes → base32 lowercase sans padding)
  - auth_secret_b64 : 43 chars (32 bytes → base64url sans padding)
  - dkey_b64 : 43 chars (32 bytes → base64url sans padding)
  - hmac_b64 : 22 chars (16 bytes → base64url sans padding)
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from uuid import UUID

from harpocrate.exceptions import InvalidTokenError, TokenExpiredError

_TOKEN_PREFIX = "hrpv"
_TOKEN_VERSION = "1"

# Longueurs fixes des champs encodés (identiques au backend)
_ID_B32_LEN = 26
_AUTH_SECRET_LEN = 43
_DKEY_LEN = 43
_HMAC_LEN = 22


@dataclass(frozen=True)
class ParsedToken:
    """Champs extraits d'un token hrpv_*."""

    version: str
    api_key_id: UUID
    exp: int  # timestamp Unix, 0 = pas d'expiration
    permissions: int  # bitmap
    auth_secret_b64: str  # raw field (43 chars)
    decryption_key: bytes  # 32 bytes décodés depuis dkey_b64
    dkey_b64: str  # raw field (43 chars)
    hmac_b64: str  # raw field — non vérifié côté client


def _b32_to_uuid(b32: str) -> UUID:
    """Décode un base32 lowercase 26 chars en UUID."""
    padded = (b32.upper() + "======")[:32]
    raw = base64.b32decode(padded)
    return UUID(bytes=raw)


def parse_token(token: str) -> ParsedToken:
    """Parse un token hrpv_* et retourne les champs décodés.

    Lève :
    - InvalidTokenError si le format est invalide
    - TokenExpiredError si le token est expiré

    N'effectue AUCUNE vérification HMAC (clé serveur uniquement).

    Stratégie de parsing positionnel : les 3 derniers champs ont des longueurs fixes
    pour gérer les '_' éventuels dans les encodages base64url.
    """
    if not isinstance(token, str) or not token.startswith(f"{_TOKEN_PREFIX}_"):
        raise InvalidTokenError("invalid_prefix", "Token must start with 'hrpv_'")

    # Longueur minimale
    min_len = (
        len(_TOKEN_PREFIX)
        + 1  # "hrpv_"
        + 1
        + 1  # version + "_"
        + _ID_B32_LEN
        + 1  # id + "_"
        + 1
        + 1  # exp (min 1 char) + "_"
        + 2
        + 1  # perms_hex + "_"
        + _AUTH_SECRET_LEN
        + 1  # auth + "_"
        + _DKEY_LEN
        + 1  # dkey + "_"
        + _HMAC_LEN  # hmac
    )
    if len(token) < min_len:
        raise InvalidTokenError("invalid_format", "Token is too short")

    # Extraction depuis la fin (champs à longueur fixe)
    hmac_b64 = token[-_HMAC_LEN:]
    if token[-(_HMAC_LEN + 1)] != "_":
        raise InvalidTokenError("invalid_format", "Malformed token structure")

    dkey_end = _HMAC_LEN + 1 + _DKEY_LEN
    dkey_b64 = token[-dkey_end : -(_HMAC_LEN + 1)]
    if token[-(dkey_end + 1)] != "_":
        raise InvalidTokenError("invalid_format", "Malformed token structure")

    auth_end = dkey_end + 1 + _AUTH_SECRET_LEN
    auth_secret_b64 = token[-auth_end : -(dkey_end + 1)]
    if token[-(auth_end + 1)] != "_":
        raise InvalidTokenError("invalid_format", "Malformed token structure")

    suffix_len = _AUTH_SECRET_LEN + 1 + _DKEY_LEN + 1 + _HMAC_LEN
    prefix_part = token[: -(suffix_len + 1)]

    early_parts = prefix_part.split("_")
    if len(early_parts) != 5:  # hrpv, v, id, exp, perms
        raise InvalidTokenError("invalid_format", "Malformed token structure (prefix)")

    prefix, version, id_b32, exp_b36, perms_hex = early_parts

    if prefix != _TOKEN_PREFIX:  # pragma: no cover
        raise InvalidTokenError("invalid_prefix", "Token must start with 'hrpv_'")

    if version != _TOKEN_VERSION:
        raise InvalidTokenError("unsupported_version", f"Unsupported token version: {version}")

    if len(id_b32) != _ID_B32_LEN:
        raise InvalidTokenError("invalid_id_encoding", "Invalid API key ID encoding")

    try:
        api_key_id = _b32_to_uuid(id_b32)
    except Exception as exc:
        raise InvalidTokenError("invalid_id_encoding", "Cannot decode API key ID") from exc

    try:
        exp = int(exp_b36, 36)
    except ValueError as exc:
        raise InvalidTokenError("invalid_exp_encoding", "Cannot decode expiration") from exc

    try:
        perms = int(perms_hex, 16)
    except ValueError as exc:
        raise InvalidTokenError("invalid_perms_encoding", "Cannot decode permissions") from exc

    if perms < 0 or perms > 0x3F:
        raise InvalidTokenError("invalid_perms_value", f"Permissions bitmap out of range: {perms}")

    try:
        # Ajoute le padding nécessaire pour base64url
        dkey_bytes = base64.urlsafe_b64decode(dkey_b64 + "==")
    except Exception as exc:
        raise InvalidTokenError("invalid_dkey_encoding", "Cannot decode decryption key") from exc

    if len(dkey_bytes) != 32:
        raise InvalidTokenError(
            "invalid_dkey_length",
            f"Decryption key must be 32 bytes, got {len(dkey_bytes)}",
        )

    # Vérification expiration (après décodage complet)
    if exp != 0 and exp < int(time.time()):
        raise TokenExpiredError("Token has expired")

    return ParsedToken(
        version=version,
        api_key_id=api_key_id,
        exp=exp,
        permissions=perms,
        auth_secret_b64=auth_secret_b64,
        decryption_key=dkey_bytes,
        dkey_b64=dkey_b64,
        hmac_b64=hmac_b64,
    )


def has_permission(parsed: ParsedToken, perm_bit: int) -> bool:
    """Vérifie si le token possède un bit de permission donné."""
    return bool(parsed.permissions & perm_bit)
