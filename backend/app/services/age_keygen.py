"""Génération d'une paire de clés AGE pour les backups (LOT_56).

Utilise le binaire `age-keygen` (paquet age, installé dans le Dockerfile).
La clé privée est retournée UNE SEULE FOIS au caller — JAMAIS persistée
côté serveur (zero-knowledge : seul l'admin la possède pour pouvoir
restaurer les backups).
"""

from __future__ import annotations

import asyncio
import re

from app.core.logging import logger


class AgeKeygenError(Exception):
    """Erreur lors de la génération de la paire AGE."""


_PUBLIC_KEY_RE = re.compile(r"^age1[a-z0-9]{50,}$", re.MULTILINE)
_PRIVATE_KEY_RE = re.compile(r"^AGE-SECRET-KEY-1[A-Z0-9]{50,}$", re.MULTILINE)
_PUBLIC_KEY_COMMENT_RE = re.compile(
    r"^#\s*public key:\s*(age1[a-z0-9]+)\s*$", re.MULTILINE | re.IGNORECASE
)


async def generate_age_keypair() -> tuple[str, str]:
    """Génère une nouvelle paire AGE et retourne `(public_key, private_key)`.

    Stratégie : appel à `age-keygen` (sans -o pour écrire sur stdout).
    Le format de sortie standard d'age-keygen :

        # created: 2026-05-06T...
        # public key: age1qyqszqgpqyqszqgpqyqszqgpqyqszqgpq...
        AGE-SECRET-KEY-1QYQSZQGPQYQSZQGPQYQSZQGPQYQSZQGPQ...

    On parse la clé publique depuis le commentaire `# public key:` et la clé
    privée depuis la ligne `AGE-SECRET-KEY-1...`.
    """
    proc = await asyncio.create_subprocess_exec(
        "age-keygen",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip() or "no stderr"
        raise AgeKeygenError(f"age-keygen exited with code {proc.returncode}: {err}")

    text = stdout.decode("utf-8", errors="replace")

    public_match = _PUBLIC_KEY_COMMENT_RE.search(text)
    private_match = _PRIVATE_KEY_RE.search(text)

    if not public_match or not private_match:
        # Fallback : essaie de récupérer la clé publique directement (rare).
        fallback_pub = _PUBLIC_KEY_RE.search(text)
        if fallback_pub and private_match:
            logger.warning("age_keygen_unusual_output_format")
            return fallback_pub.group(0), private_match.group(0)
        raise AgeKeygenError(
            "could not parse age-keygen output (format unexpected)"
        )

    public_key = public_match.group(1)
    private_key = private_match.group(0)
    logger.info("age_keypair_generated", public_key_prefix=public_key[:12])
    return public_key, private_key
