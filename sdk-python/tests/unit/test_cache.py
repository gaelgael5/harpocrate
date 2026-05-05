"""Tests du cache wallet_key — LOT_09 SDK."""

from __future__ import annotations

import os
import time

from harpocrate.cache import WalletKeyCache


class TestWalletKeyCache:
    """Tests du cache en mémoire avec TTL."""

    def test_get_after_set(self) -> None:
        """Une valeur set() est retrouvée par get()."""
        cache = WalletKeyCache(ttl_seconds=60)
        key = os.urandom(32)
        cache.set("wallet-1", key)
        assert cache.get("wallet-1") == key

    def test_get_unknown_key_returns_none(self) -> None:
        """get() retourne None pour une clé inconnue."""
        cache = WalletKeyCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self) -> None:
        """Une entrée expirée n'est plus retournée."""
        cache = WalletKeyCache(ttl_seconds=1)
        key = os.urandom(32)
        cache.set("wallet-1", key)
        time.sleep(1.1)  # Attendre l'expiration
        assert cache.get("wallet-1") is None

    def test_ttl_not_expired(self) -> None:
        """Une entrée non expirée est toujours retournée."""
        cache = WalletKeyCache(ttl_seconds=10)
        key = os.urandom(32)
        cache.set("wallet-1", key)
        time.sleep(0.1)
        assert cache.get("wallet-1") == key

    def test_clear_removes_all(self) -> None:
        """clear() supprime toutes les entrées."""
        cache = WalletKeyCache()
        cache.set("w1", os.urandom(32))
        cache.set("w2", os.urandom(32))
        cache.clear()
        assert cache.get("w1") is None
        assert cache.get("w2") is None

    def test_invalidate_removes_specific_entry(self) -> None:
        """invalidate() supprime une entrée spécifique."""
        cache = WalletKeyCache()
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        cache.set("w1", key1)
        cache.set("w2", key2)
        cache.invalidate("w1")
        assert cache.get("w1") is None
        assert cache.get("w2") == key2

    def test_maxsize_eviction(self) -> None:
        """Quand le cache est plein, l'entrée la plus ancienne est évincée."""
        cache = WalletKeyCache(ttl_seconds=60, maxsize=3)
        cache.set("w1", os.urandom(32))
        cache.set("w2", os.urandom(32))
        cache.set("w3", os.urandom(32))
        # Ajouter une 4e entrée → éviction d'une des 3 premières
        cache.set("w4", os.urandom(32))
        # Le cache ne doit pas dépasser maxsize
        count = sum(1 for k in ("w1", "w2", "w3", "w4") if cache.get(k) is not None)
        assert count <= 3

    def test_thread_safety(self) -> None:
        """Le cache est thread-safe (pas de race condition)."""
        import threading

        cache = WalletKeyCache(ttl_seconds=60, maxsize=100)
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(50):
                    cache.set(f"k{i}", os.urandom(32))
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                for i in range(50):
                    cache.get(f"k{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
