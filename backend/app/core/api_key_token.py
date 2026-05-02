"""Encode/decode du token hrpv_* et calcul HMAC — LOT_08.

Format : hrpv_{v}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64url}_{dkey_b64url}_{hmac_b64url}
- 8 segments séparés par '_'
- Le HMAC couvre : "{v}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64url}"
- decryption_key N'EST PAS dans le HMAC (jamais envoyé au serveur lors de la validation)
- hmac_truncated = HMAC-SHA256(master_key, message)[:16]  → 22 chars base64url sans padding
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from uuid import UUID

_TOKEN_PREFIX = "hrpv"
_TOKEN_VERSION = "1"
_SEGMENT_COUNT = 8  # hrpv + v + id + exp + perms + auth_secret + dkey + hmac

# Longueurs fixes des champs encodés
_ID_B32_LEN = 26      # UUID 16 bytes → base32 lowercase sans padding
_AUTH_SECRET_LEN = 43  # 32 bytes → base64url sans padding
_DKEY_LEN = 43         # 32 bytes → base64url sans padding
_HMAC_LEN = 22         # 16 bytes → base64url sans padding


@dataclass(frozen=True)
class ParsedToken:
    """Résultat du parsing d'un token hrpv_*."""

    version: str
    api_key_id: UUID
    api_key_id_b32: str   # représentation brute (26 chars lowercase)
    exp: int              # timestamp Unix, 0 = pas d'expiration
    exp_b36: str          # représentation brute
    perms: int
    perms_hex: str        # représentation brute (2 chars)
    auth_secret_b64: str  # représentation brute
    dkey_b64: str         # représentation brute
    hmac_b64: str         # représentation brute


# ─── Encoding helpers ─────────────────────────────────────────────────────────


def _uuid_to_b32(uid: UUID) -> str:
    """Encode un UUID en base32 lowercase 26 chars sans padding."""
    raw = uid.bytes  # 16 bytes
    encoded = base64.b32encode(raw).decode().lower()
    # base32 de 16 bytes = 26 chars + 6 '=' padding
    return encoded.rstrip("=")


def _b32_to_uuid(b32: str) -> UUID:
    """Décode un base32 lowercase 26 chars en UUID."""
    # base32 nécessite du padding pour être un multiple de 8
    padded = (b32.upper() + "======")[:32]  # 26 chars + 6 '=' = 32, multiple de 8
    raw = base64.b32decode(padded)
    return UUID(bytes=raw)


def _exp_to_b36(exp: int) -> str:
    """Encode un entier en base36."""
    if exp == 0:
        return "0"
    digits = []
    n = exp
    while n:
        digits.append("0123456789abcdefghijklmnopqrstuvwxyz"[n % 36])
        n //= 36
    return "".join(reversed(digits))


def _b36_to_int(b36: str) -> int:
    """Décode un base36 en entier."""
    return int(b36, 36)


def _perms_to_hex(perms: int) -> str:
    """Encode un bitmap de permissions en hex 2 chars (ex : 0x05 → '05')."""
    return f"{perms:02x}"


def _hex_to_perms(h: str) -> int:
    """Décode un hex 2 chars en entier."""
    return int(h, 16)


# ─── HMAC ─────────────────────────────────────────────────────────────────────


def compute_hmac(
    master_key_b64: str,
    *,
    version: str,
    id_b32: str,
    exp_b36: str,
    perms_hex: str,
    auth_secret_b64: str,
) -> str:
    """Calcule le HMAC-SHA256 tronqué à 16 bytes, encodé en base64url sans padding.

    Le message signé est : "{version}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64}"
    decryption_key est EXCLU du HMAC intentionnellement (jamais renvoyé au serveur).
    """
    master_key = base64.b64decode(master_key_b64)
    message = f"{version}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64}".encode()
    full = hmac.new(master_key, message, hashlib.sha256).digest()
    truncated = full[:16]
    return base64.urlsafe_b64encode(truncated).rstrip(b"=").decode()


def verify_hmac(
    master_key_b64: str,
    *,
    version: str,
    id_b32: str,
    exp_b36: str,
    perms_hex: str,
    auth_secret_b64: str,
    given_hmac_b64: str,
) -> bool:
    """Vérifie le HMAC en constant-time. Retourne True si valide."""
    expected = compute_hmac(
        master_key_b64,
        version=version,
        id_b32=id_b32,
        exp_b36=exp_b36,
        perms_hex=perms_hex,
        auth_secret_b64=auth_secret_b64,
    )
    return hmac.compare_digest(expected, given_hmac_b64)


# ─── Encode / Decode ──────────────────────────────────────────────────────────


def encode_token(
    *,
    api_key_id: UUID,
    exp: int,
    perms: int,
    auth_secret_b64: str,
    dkey_b64: str,
    master_key_b64: str,
) -> str:
    """Assemble le token hrpv_* complet.

    Paramètres :
    - api_key_id : UUID de la clé en DB
    - exp : timestamp Unix d'expiration (0 = pas d'expiration)
    - perms : bitmap de permissions (0x01..0x3F)
    - auth_secret_b64 : auth_secret encodé base64url sans padding (43 chars)
    - dkey_b64 : decryption_key encodé base64url sans padding (43 chars)
    - master_key_b64 : HARPOCRATE_HMAC_KEY (base64 standard, 32 bytes)
    """
    v = _TOKEN_VERSION
    id_b32 = _uuid_to_b32(api_key_id)
    exp_b36 = _exp_to_b36(exp)
    perms_hex = _perms_to_hex(perms)

    hmac_b64 = compute_hmac(
        master_key_b64,
        version=v,
        id_b32=id_b32,
        exp_b36=exp_b36,
        perms_hex=perms_hex,
        auth_secret_b64=auth_secret_b64,
    )

    fields = f"{v}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64}_{dkey_b64}_{hmac_b64}"
    return f"{_TOKEN_PREFIX}_{fields}"


class TokenParseError(Exception):
    """Erreur de parsing du token — code d'erreur inclus."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def parse_token(token: str) -> ParsedToken:
    """Parse un token hrpv_* et retourne les champs décodés.

    Lève TokenParseError avec un error_code en cas d'erreur.
    N'effectue AUCUN appel DB ni vérification HMAC.

    Stratégie de parsing positionnel :
    Les champs auth_secret, dkey et hmac sont en base64url et peuvent contenir '_'.
    On ne peut donc pas splitter naïvement sur '_'.
    On parse en utilisant les longueurs connues des champs depuis la fin :
    - hmac : 22 chars (fixe)
    - dkey : 43 chars (fixe)
    - auth_secret : 43 chars (fixe)
    Les champs variables (exp_b36) sont récupérés par split sur le début.
    """
    # Vérif longueur minimale : "hrpv_1_" + 26 + "_" + "0" + "_" + "xx" + "_"
    # + 43 + "_" + 43 + "_" + 22 = 7+26+1+1+1+2+1+43+1+43+1+22 = 149 chars minimum
    if not token.startswith(f"{_TOKEN_PREFIX}_"):
        raise TokenParseError("invalid_prefix")

    # Parsing depuis la fin : les 3 derniers champs ont des longueurs fixes.
    # Token = prefix_version_id_exp_perms_authsecret_dkey_hmac
    # On extrait depuis la fin :
    # - hmac_b64 = derniers 22 chars (précédé de '_')
    # - dkey_b64 = 43 chars avant ça (précédé de '_')
    # - auth_secret_b64 = 43 chars avant ça (précédé de '_')
    # - Le reste = "hrpv_v_id_exp_perms" qu'on peut splitter naïvement (pas de b64url)
    min_len = (
        len(_TOKEN_PREFIX) + 1  # "hrpv_"
        + 1 + 1  # v + "_"
        + _ID_B32_LEN + 1  # id + "_"
        + 1 + 1  # exp (min 1 char) + "_"
        + 2 + 1  # perms_hex + "_"
        + _AUTH_SECRET_LEN + 1  # auth + "_"
        + _DKEY_LEN + 1  # dkey + "_"
        + _HMAC_LEN  # hmac
    )
    if len(token) < min_len:
        raise TokenParseError("invalid_format")

    # Extrait depuis la fin — les offsets sont calculés à partir de la fin du token.
    # Suffixes : ..._{auth_secret}_{dkey}_{hmac}
    _hmac_end = _HMAC_LEN
    _dkey_end = _hmac_end + 1 + _DKEY_LEN
    _auth_end = _dkey_end + 1 + _AUTH_SECRET_LEN

    hmac_b64 = token[-_hmac_end:]
    if token[-(_hmac_end + 1)] != "_":
        raise TokenParseError("invalid_format")

    dkey_b64 = token[-_dkey_end: -(_hmac_end + 1)]
    if token[-(_dkey_end + 1)] != "_":
        raise TokenParseError("invalid_format")

    auth_secret_b64 = token[-_auth_end: -(_dkey_end + 1)]
    if token[-(_auth_end + 1)] != "_":
        raise TokenParseError("invalid_format")

    # Préfixe = tout ce qui précède les 3 champs b64url
    suffix_len = _AUTH_SECRET_LEN + 1 + _DKEY_LEN + 1 + _HMAC_LEN
    prefix_part = token[:-(suffix_len + 1)]  # +1 pour le '_' avant auth_secret

    # Le préfixe n'a pas de b64url → split simple
    early_parts = prefix_part.split("_")
    if len(early_parts) != 5:  # hrpv, v, id, exp, perms
        raise TokenParseError("invalid_format")

    prefix, version, id_b32, exp_b36, perms_hex = early_parts

    if prefix != _TOKEN_PREFIX:
        raise TokenParseError("invalid_prefix")  # pragma: no cover — déjà vérifié

    if version != _TOKEN_VERSION:
        raise TokenParseError("unsupported_version")

    if len(id_b32) != _ID_B32_LEN:
        raise TokenParseError("invalid_id_encoding")

    # Décodage api_key_id
    try:
        api_key_id = _b32_to_uuid(id_b32)
    except Exception as exc:
        raise TokenParseError("invalid_id_encoding") from exc

    # Décodage expiration
    try:
        exp = _b36_to_int(exp_b36)
    except Exception as exc:
        raise TokenParseError("invalid_exp_encoding") from exc

    # Décodage permissions
    try:
        perms = _hex_to_perms(perms_hex)
    except Exception as exc:
        raise TokenParseError("invalid_perms_encoding") from exc

    if perms < 0 or perms > 0x3F:
        raise TokenParseError("invalid_perms_value")

    return ParsedToken(
        version=version,
        api_key_id=api_key_id,
        api_key_id_b32=id_b32,
        exp=exp,
        exp_b36=exp_b36,
        perms=perms,
        perms_hex=perms_hex,
        auth_secret_b64=auth_secret_b64,
        dkey_b64=dkey_b64,
        hmac_b64=hmac_b64,
    )


def is_expired(exp: int) -> bool:
    """Retourne True si le token est expiré. exp=0 signifie pas d'expiration."""
    if exp == 0:
        return False
    return exp < int(time.time())
