"""Cache en RAM pour la wallet_key déchiffrée — LOT_09 SDK.

La wallet_key est déchiffrée une fois depuis le token (decryption_key)
puis mise en cache pour éviter de la redériver à chaque appel.

Sécurité :
- Le cache est en mémoire uniquement, jamais persisté.
- TTL configurable (défaut 600s = 10 min).
- Si l'API key est révoquée, le serveur retournera 401 au prochain appel HTTP.
  Le cache local peut continuer à fonctionner jusqu'au TTL expiry (acceptable MVP).
"""

from __future__ import annotations

import threading
import time


class WalletKeyCache:
    """Cache LRU + TTL simple pour stocker la wallet_key déchiffrée.

    Utilise un simple dict avec expiry timestamp (pas de dépendance cachetools
    pour minimiser les imports du SDK).

    Thread-safe via un Lock.
    """

    def __init__(self, ttl_seconds: int = 600, maxsize: int = 16) -> None:
        """Initialise le cache.

        Paramètres :
            ttl_seconds : durée de vie d'une entrée en secondes (défaut 600).
            maxsize : nombre maximum d'entrées (LRU, les plus vieilles expirent).
        """
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._store: dict[str, tuple[bytes, float]] = {}  # key → (value, expire_at)
        self._lock = threading.Lock()

    def get(self, cache_key: str) -> bytes | None:
        """Retourne la valeur si elle existe et n'est pas expirée, None sinon."""
        with self._lock:
            entry = self._store.get(cache_key)
            if entry is None:
                return None
            value, expire_at = entry
            if time.monotonic() > expire_at:
                del self._store[cache_key]
                return None
            return value

    def set(self, cache_key: str, value: bytes) -> None:
        """Stocke une valeur avec TTL.

        Si le cache est plein, l'entrée avec l'expiry la plus proche est évincée.
        """
        with self._lock:
            if len(self._store) >= self._maxsize and cache_key not in self._store:
                # Éviction de l'entrée avec expire_at le plus proche (LRU approximatif)
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
            expire_at = time.monotonic() + self._ttl
            self._store[cache_key] = (value, expire_at)

    def clear(self) -> None:
        """Vide tout le cache."""
        with self._lock:
            self._store.clear()

    def invalidate(self, cache_key: str) -> None:
        """Supprime une entrée spécifique du cache."""
        with self._lock:
            self._store.pop(cache_key, None)
