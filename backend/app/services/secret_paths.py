"""Validation et normalisation des noms de secrets avec paths (LOT_18)."""
from __future__ import annotations

import re


class InvalidSecretPath(Exception):
    """Levée quand un nom de secret ne respecte pas les règles de path.

    N'hérite PAS de ValueError pour ne pas être interceptée par les
    field_validator Pydantic (qui convertissent ValueError en 422).
    Mappée par un handler FastAPI global vers 400 invalid_secret_path.
    """


_ROOT_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9@._-]+$")
_MAX_DEPTH = 10


def validate_secret_name(name: str) -> str:
    """Valide et normalise un nom de secret (peut contenir des '/').

    - Sans '/' → doit matcher [A-Za-z0-9_.-] (env-var safe)
    - Avec '/' → '/' initial ajouté si absent, pas de '/' final

    Lève ValueError si invalide.
    """
    if "/" not in name:
        if not _ROOT_NAME_RE.match(name):
            raise ValueError(
                f"Invalid secret name '{name}': only [A-Za-z0-9_.-] allowed for root secrets"
            )
        return name

    normalized = name if name.startswith("/") else "/" + name

    if "//" in normalized:
        raise ValueError("Empty path segments not allowed (found '//')")

    segments = [s for s in normalized.split("/") if s]

    if len(segments) > _MAX_DEPTH + 1:
        raise ValueError(f"Path too deep (max {_MAX_DEPTH} levels, got {len(segments) - 1})")

    for seg in segments:
        if seg in (".", ".."):
            raise ValueError("Relative path navigation not allowed ('.' or '..')")
        if not _SEGMENT_RE.match(seg):
            raise ValueError(
                f"Invalid path segment '{seg}': only [a-zA-Z0-9@._-] allowed"
            )

    return normalized


def normalize_path(path: str | None) -> str:
    """Normalise un path de répertoire : '/' final garanti, '' → '/'.

    Utilisé pour les paramètres ?path= des endpoints /tree et /secrets.
    """
    if not path or path == "/":
        return "/"
    normalized = path if path.startswith("/") else "/" + path
    return normalized if normalized.endswith("/") else normalized + "/"
