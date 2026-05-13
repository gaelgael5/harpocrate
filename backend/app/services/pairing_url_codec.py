"""Génération et parsing d'une URL d'appairage (LOT 5 — v2).

Remplace le code 4 chiffres v1 par une URL signée à copier-coller : l'admin
master colle l'URL publique du standby, reçoit en retour une URL d'appairage
qui contient `master_url` + `session_id` + `token`. Le standby colle cette URL
unique, le backend la parse et contacte le master directement.

Format : `<master_public_url>/pair?sid=<UUID>&t=<TOKEN>`

Le token est un secret aléatoire 128 bits encodé en hex (32 caractères),
stocké en clair côté master dans `pairing_session.code` (même mécanisme que
le code 4 chiffres v1, juste avec une entropie nettement supérieure et un
TTL identique).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from uuid import UUID

# 16 bytes = 128 bits d'entropie, encodés en 32 caractères hex.
_TOKEN_BYTES = 16
_TOKEN_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_PAIR_PATH = "/pair"


class InvalidPairingUrlError(Exception):
    """L'URL collée n'est pas une URL d'appairage valide."""


@dataclass(frozen=True)
class ParsedPairingUrl:
    master_url: str
    session_id: UUID
    token: str


def generate_token() -> str:
    """Token aléatoire 128 bits, hex 32 chars."""
    return secrets.token_hex(_TOKEN_BYTES)


def build_pairing_url(master_public_url: str, session_id: UUID, token: str) -> str:
    """Construit l'URL d'appairage à transmettre au standby.

    `master_public_url` est l'URL publique du backend Harpocrate du master
    (settings.public_url). On retire un éventuel slash final pour éviter
    `https://master//pair?...`.
    """
    if not _TOKEN_RE.match(token):
        raise ValueError("token_must_be_32_hex_chars")
    base = master_public_url.rstrip("/")
    return f"{base}{_PAIR_PATH}?sid={session_id}&t={token}"


def parse_pairing_url(url: str) -> ParsedPairingUrl:
    """Parse l'URL d'appairage en (master_url, session_id, token).

    `master_url` est reconstruit en stripant `/pair?...` : le standby pourra
    ensuite construire l'URL des endpoints du master à partir de cette base.

    Raises InvalidPairingUrlError si l'URL ne matche pas le format attendu.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError as e:
        raise InvalidPairingUrlError(f"url_unparseable:{e}") from e

    if parsed.scheme not in ("http", "https"):
        raise InvalidPairingUrlError(f"invalid_scheme:{parsed.scheme!r}")
    if not parsed.hostname:
        raise InvalidPairingUrlError("missing_hostname")
    if parsed.path.rstrip("/") != _PAIR_PATH:
        raise InvalidPairingUrlError(f"invalid_path:{parsed.path!r}")

    qs = parse_qs(parsed.query)
    sid_raw = qs.get("sid", [None])[0]
    token = qs.get("t", [None])[0]
    if not sid_raw or not token:
        raise InvalidPairingUrlError("missing_sid_or_token")
    try:
        sid = UUID(sid_raw)
    except ValueError as e:
        raise InvalidPairingUrlError(f"invalid_sid:{sid_raw!r}") from e
    if not _TOKEN_RE.match(token):
        raise InvalidPairingUrlError("invalid_token_format")

    # Reconstruit la base sans le path /pair ni la query.
    port_part = f":{parsed.port}" if parsed.port else ""
    master_url = f"{parsed.scheme}://{parsed.hostname}{port_part}"

    return ParsedPairingUrl(master_url=master_url, session_id=sid, token=token)
