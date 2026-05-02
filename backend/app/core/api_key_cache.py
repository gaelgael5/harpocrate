"""Cache TTL en mémoire pour la validation des API keys — LOT_08.

Deux caches distincts :
1. Validation cache : (api_key_id_str, sha256_hex(auth_secret_b64)) → bool (valid ou non)
   TTL : HARPOCRATE_API_KEY_VALIDATION_CACHE_TTL_SECONDS (défaut 60s)
2. Wallet cache : wallet_id_str → données (non utilisé directement ici — extensible)

Note implémentation :
- Utilise time.monotonic() pour les TTL (insensible aux sauts d'horloge système).
- Simple dict Python — pas de Redis. Acceptable pour MVP mono-instance.
- Thread-safety : asyncio est single-threaded, pas de locking nécessaire.
- Invalidation explicite à la révocation.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from uuid import UUID


@dataclass
class _CacheEntry:
    valid: bool
    expires_at: float  # time.monotonic()


# ─── Validation cache ─────────────────────────────────────────────────────────

_validation_cache: dict[str, _CacheEntry] = {}


def _validation_key(api_key_id: UUID, auth_secret_b64: str) -> str:
    """Clé de cache : (api_key_id, sha256(auth_secret_b64)).

    On hache auth_secret_b64 pour éviter de stocker le secret en clair dans la clé.
    La clé inclut api_key_id pour éviter les collisions inter-clés.
    """
    digest = hashlib.sha256(auth_secret_b64.encode()).hexdigest()
    return f"{api_key_id}:{digest}"


def cache_get_valid(api_key_id: UUID, auth_secret_b64: str) -> bool | None:
    """Retourne True/False si en cache, None si absent ou expiré."""
    key = _validation_key(api_key_id, auth_secret_b64)
    entry = _validation_cache.get(key)
    if entry is None:
        return None
    if time.monotonic() > entry.expires_at:
        del _validation_cache[key]
        return None
    return entry.valid


def cache_set_valid(api_key_id: UUID, auth_secret_b64: str, *, valid: bool) -> None:
    """Stocke le résultat de validation dans le cache."""
    from app.core.config import settings  # lazy import — évite init au module load

    key = _validation_key(api_key_id, auth_secret_b64)
    ttl = settings.api_key_validation_cache_ttl_seconds
    _validation_cache[key] = _CacheEntry(valid=valid, expires_at=time.monotonic() + ttl)


def cache_invalidate(api_key_id: UUID) -> None:
    """Invalide toutes les entrées pour un api_key_id donné (à la révocation).

    Parcourt le cache et supprime les entrées dont la clé commence par l'id.
    O(n) acceptable pour MVP (taille du cache bornée par le nb de clés actives).
    """
    prefix = str(api_key_id) + ":"
    keys_to_delete = [k for k in _validation_cache if k.startswith(prefix)]
    for k in keys_to_delete:
        del _validation_cache[k]


def cache_clear_all() -> None:
    """Vide tout le cache — utilitaire pour les tests."""
    _validation_cache.clear()
