"""Rotation détectée par auth_error (LOT_22).

Pattern d'usage :

```python
@client.on_auth_error("anthropic_api_key")
async def on_rotation(new_value: str) -> None:
    anthropic.api_key = new_value

# Quand l'app détecte un 401 sur un appel utilisant ce secret :
await client.notify_auth_error("anthropic_api_key")
```

Le SDK refait un GET forcé du secret, déchiffre, puis appelle les callbacks
enregistrés. Si le refresh échoue, `SecretRefreshFailed` est levée.

Les callbacks peuvent être sync ou async — le SDK gère les deux.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("harpocrate.rotation")

# Type alias : callback peut être sync ou async, signature varie
SpecificCallback = Callable[[str], None] | Callable[[str], Awaitable[None]]
GlobalCallback = (
    Callable[[str, str], None] | Callable[[str, str], Awaitable[None]]
)


class RotationRegistry:
    """Registre des callbacks de rotation par secret + global."""

    def __init__(self) -> None:
        self._specific: dict[str, list[SpecificCallback]] = defaultdict(list)
        self._global: list[GlobalCallback] = []

    def register_specific(
        self,
        secret_name: str,
        callback: SpecificCallback,
    ) -> SpecificCallback:
        """Enregistre un callback pour un secret nommé. Retourne le callback (decorator-friendly)."""
        self._specific[secret_name].append(callback)
        return callback

    def register_global(self, callback: GlobalCallback) -> GlobalCallback:
        """Enregistre un callback global (tous les secrets)."""
        self._global.append(callback)
        return callback

    async def fire(self, secret_name: str, new_value: str) -> None:
        """Déclenche tous les callbacks pour ce secret + globaux. Ordre : specific → global.

        Les exceptions des callbacks sont loggées mais NE bloquent PAS l'enchaînement.
        """
        for cb in self._specific.get(secret_name, []):
            await self._invoke(cb, secret_name, new_value)
        for cb in self._global:
            await self._invoke(cb, secret_name, new_value, global_=True)

    @staticmethod
    async def _invoke(
        callback: Any,
        secret_name: str,
        new_value: str,
        *,
        global_: bool = False,
    ) -> None:
        try:
            result = (
                callback(secret_name, new_value) if global_ else callback(new_value)
            )
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "rotation_callback_failed secret=%s callback=%s error=%s",
                secret_name,
                getattr(callback, "__name__", repr(callback)),
                exc,
            )

    def fire_sync(self, secret_name: str, new_value: str) -> None:
        """Variante synchrone — utilisée depuis du code non-async.

        Si on est dans un event loop actif, on schedule la coroutine ;
        sinon on bloque sur asyncio.run().
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.fire(secret_name, new_value))
            return
        # Loop actif → on planifie sans bloquer le caller
        loop.create_task(self.fire(secret_name, new_value))

    def clear(self) -> None:
        """Vide le registre — utile pour les tests."""
        self._specific.clear()
        self._global.clear()
