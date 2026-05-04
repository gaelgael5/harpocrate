# Lot 22 — SDK Python : détection de rotation et reconnexion automatique

> **Prérequis** : Lots 00-21, et en particulier lot 09 (SDK Python v0.2.0).
> **Langage** : Python uniquement. npm et CLI Bash dans des lots futurs.

## Objectif

Étendre le SDK Python Harpocrate pour détecter automatiquement les **rotations de secrets** et les **révocations d'API keys** à travers les erreurs d'authentification retournées par l'API. Quand une erreur 401/403 est détectée lors de l'utilisation d'un secret, le SDK tente un refresh automatique, notifie l'application via des callbacks enregistrés, et réessaie. Si le refresh échoue, une exception claire est remontée.

## Modèle de fonctionnement (Option D2)

```
Application                    SDK                        Harpocrate
    │                           │                              │
    │  get_secret("key")        │                              │
    ├──────────────────────────►│                              │
    │                           │  GET /secrets/key            │
    │                           ├─────────────────────────────►│
    │                           │  200 + encrypted_value       │
    │                           │◄─────────────────────────────│
    │  "sk-ant-..."             │  déchiffre                   │
    │◄──────────────────────────│                              │
    │                           │                              │
    │  [application utilise la valeur]                         │
    │                           │                              │
    │  [secret rotaté côté Harpocrate — SDK ne le sait pas]    │
    │                           │                              │
    │  [application reçoit 401 de l'API tierce]                │
    │                           │                              │
    │  notify_auth_error("key") │                              │
    ├──────────────────────────►│                              │
    │                           │  force refresh               │
    │                           │  GET /secrets/key            │
    │                           ├─────────────────────────────►│
    │                           │  200 + nouvelle valeur       │
    │                           │◄─────────────────────────────│
    │                           │  déchiffre                   │
    │                           │                              │
    │                           │  appelle callback            │
    │                           │  on_auth_error("key", new)   │
    │◄──────────────────────────│                              │
    │                           │                              │
    │  [application met à jour son client avec la nouvelle valeur]
```

---

## Périmètre

### Inclus

- `client.on_auth_error(secret_name, callback)` — callback par secret nommé
- `client.on_any_auth_error(callback)` — callback global (tous les secrets)
- `client.notify_auth_error(secret_name)` — déclenché par l'application quand elle détecte un 401
- `client.get_secret(secret_name, force_refresh=True)` — force un refetch immédiat
- Retry automatique dans `notify_auth_error` : refresh + appel callback + 1 retry
- Exception `SecretRefreshFailed` si le refresh échoue
- Context manager `client.using_secret(secret_name)` — sucre syntaxique optionnel qui gère retry automatique
- Tests complets
- Documentation mise à jour
- Bump version `harpocrate-sdk` → `0.3.0`
- Publication PyPI (sdist)

### Exclus

- Pas de polling (pas de TTL, pas de background task)
- Pas de push serveur (pas de SSE, pas de webhook)
- Pas de SDK npm ni CLI Bash (lots futurs)
- Pas de détection proactive côté serveur (le serveur ne notifie pas le SDK)

---

## Spécifications fonctionnelles

### `client.on_auth_error(secret_name, callback)`

Enregistre un callback appelé quand `notify_auth_error(secret_name)` est déclenché et que le refresh réussit.

```python
@client.on_auth_error("anthropic_api_key")
async def handle_anthropic_rotation(new_value: str) -> None:
    """Appelé avec la nouvelle valeur déchiffrée."""
    anthropic_client.api_key = new_value
    logger.info("anthropic_api_key rotated, client updated")
```

- Le décorateur enregistre le callback dans un registre interne
- Plusieurs callbacks peuvent être enregistrés pour le même secret (appelés dans l'ordre d'enregistrement)
- Le callback reçoit **la nouvelle valeur déchiffrée** (string)
- Le callback peut être sync ou async (le SDK gère les deux)
- Si le callback lève une exception, elle est loggée mais **ne bloque pas** le retry

### `client.on_any_auth_error(callback)`

Callback global appelé pour n'importe quel secret en rotation.

```python
@client.on_any_auth_error
async def handle_any_rotation(secret_name: str, new_value: str) -> None:
    """Filet de sécurité : loguer toutes les rotations."""
    logger.warning("secret_rotated", secret=secret_name)
    metrics.increment("secret_rotation", tags={"secret": secret_name})
```

- Appelé **en plus** du callback spécifique (pas à la place)
- Ordre d'appel : callbacks spécifiques d'abord, global ensuite
- Plusieurs callbacks globaux peuvent être enregistrés

### `client.notify_auth_error(secret_name)`

Déclenché par l'application quand elle détecte une erreur d'authentification liée à un secret.

```python
async def call_anthropic_api(prompt: str) -> str:
    key = client.get_secret("anthropic_api_key")
    try:
        return await anthropic.complete(prompt, api_key=key)
    except anthropic.AuthenticationError:
        # Notifier le SDK : ce secret semble périmé
        await client.notify_auth_error("anthropic_api_key")
        # Après notify_auth_error, les callbacks ont été appelés
        # et le cache est à jour — refetch la nouvelle valeur
        new_key = client.get_secret("anthropic_api_key")
        return await anthropic.complete(prompt, api_key=new_key)
```

**Comportement interne de `notify_auth_error`** :
1. Invalider le cache pour `secret_name`
2. Refetch depuis Harpocrate (`force_refresh=True`)
3. Si refetch échoue → lever `SecretRefreshFailed` (pas de callback appelé)
4. Si refetch réussit :
   a. Mettre à jour le cache
   b. Appeler les callbacks spécifiques à `secret_name`
   c. Appeler les callbacks globaux
5. Retourner (l'application refetch avec `get_secret` si elle en a besoin)

**Note** : `notify_auth_error` est **idempotent sous lock** — si plusieurs coroutines appellent simultanément `notify_auth_error` pour le même secret, un seul refresh est effectué et tous les appelants attendent le résultat.

### `client.get_secret(secret_name, force_refresh=False)`

Existant depuis lot 09, enrichi avec `force_refresh` :

```python
# Normal : retourne depuis le cache si disponible
key = client.get_secret("anthropic_api_key")

# Forcé : bypass le cache, toujours depuis Harpocrate
key = client.get_secret("anthropic_api_key", force_refresh=True)
```

### Context manager `client.using_secret(secret_name)` (optionnel)

Sucre syntaxique qui :
1. Fournit la valeur courante du secret
2. Si l'appel dans le bloc lève une exception marquée comme auth error → déclenche `notify_auth_error` automatiquement
3. Réessaie le bloc une fois avec la nouvelle valeur

```python
# Usage basique
async with client.using_secret("anthropic_api_key") as key:
    result = await anthropic.complete(prompt, api_key=key)
# Si AuthenticationError → refresh automatique + retry

# Spécifier quelles exceptions sont des auth errors
async with client.using_secret(
    "github_token",
    auth_errors=(github.UnauthorizedError, github.ForbiddenError)
) as key:
    repos = await github.list_repos(token=key)
```

**Comportement** :
1. `key = client.get_secret(secret_name)`
2. Exécute le bloc
3. Si une exception de type `auth_errors` est levée :
   a. `await client.notify_auth_error(secret_name)` (refresh + callbacks)
   b. `key = client.get_secret(secret_name)` (nouvelle valeur)
   c. Réexécute le bloc une fois
   d. Si exception encore → laisse remonter (pas de boucle infinie)
4. Sinon → laisse remonter l'exception normalement

**Note** : le context manager ne peut pas savoir nativement quelles exceptions sont des "auth errors" pour une librairie tierce. L'application doit les spécifier via `auth_errors=`. Une liste de defaults courants est fournie :

```python
DEFAULT_AUTH_ERRORS = (
    # Génériques
    PermissionError,
    # Requests/httpx
    # (pas importé par défaut, détection duck-typing)
)
```

### Exception `SecretRefreshFailed`

```python
class SecretRefreshFailed(HarpocrateError):
    """
    Levée quand notify_auth_error ne peut pas refetch le secret.
    
    Causes possibles :
    - API key du SDK révoquée
    - Secret supprimé dans Harpocrate
    - Harpocrate inaccessible
    - Secret renommé
    """
    
    def __init__(
        self,
        secret_name: str,
        reason: str,
        http_status: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        self.secret_name = secret_name
        self.reason = reason
        self.http_status = http_status
        self.original_error = original_error
        super().__init__(
            f"Failed to refresh secret '{secret_name}': {reason}"
            + (f" (HTTP {http_status})" if http_status else "")
        )
```

Cas couverts :

| Situation | `reason` | `http_status` |
|---|---|---|
| API key SDK révoquée | `"api_key_revoked"` | 401 |
| Secret supprimé | `"secret_not_found"` | 404 |
| Harpocrate inaccessible | `"vault_unreachable"` | None |
| Permission insuffisante | `"permission_denied"` | 403 |
| Erreur interne Harpocrate | `"vault_error"` | 500 |

---

## Spécifications techniques

### Structure des fichiers

```
harpocrate_sdk/
├── __init__.py
├── client.py              # VaultClient — modifié
├── cache.py               # SecretCache — modifié (invalidation)
├── callbacks.py           # CallbackRegistry — nouveau
├── context.py             # using_secret context manager — nouveau
├── exceptions.py          # SecretRefreshFailed + existants — modifié
└── ...

tests/
├── test_callbacks.py      # nouveau
├── test_notify_auth_error.py  # nouveau
├── test_using_secret.py   # nouveau
├── test_refresh_failed.py # nouveau
└── ...
```

### `callbacks.py` — Registre des callbacks

```python
# harpocrate_sdk/callbacks.py

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Callable, Awaitable

logger = logging.getLogger("harpocrate_sdk.callbacks")

Callback = Callable[..., None | Awaitable[None]]


class CallbackRegistry:
    """Registre des callbacks de rotation de secrets."""

    def __init__(self):
        # secret_name → liste de callbacks
        self._specific: dict[str, list[Callback]] = defaultdict(list)
        # callbacks globaux (any secret)
        self._global: list[Callback] = []

    def register_specific(self, secret_name: str, callback: Callback) -> None:
        self._specific[secret_name].append(callback)

    def register_global(self, callback: Callback) -> None:
        self._global.append(callback)

    async def fire(self, secret_name: str, new_value: str) -> None:
        """Appelle tous les callbacks pour ce secret (spécifiques puis globaux)."""
        # Callbacks spécifiques
        for cb in self._specific.get(secret_name, []):
            await self._call_safely(cb, new_value, context=secret_name)

        # Callbacks globaux
        for cb in self._global:
            await self._call_safely(cb, secret_name, new_value, context="global")

    async def _call_safely(
        self,
        callback: Callback,
        *args,
        context: str,
    ) -> None:
        """Appelle un callback sans laisser une exception le bloquer."""
        try:
            result = callback(*args)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.error(
                "callback_error",
                context=context,
                callback=getattr(callback, "__name__", repr(callback)),
                error=str(e),
            )
            # Ne pas propager — le callback ne doit pas bloquer le retry
```

### `client.py` — Modifications VaultClient

```python
# harpocrate_sdk/client.py (extraits des modifications)

import asyncio
from typing import Callable, Awaitable, Optional, Type
from .callbacks import CallbackRegistry
from .exceptions import SecretRefreshFailed

class VaultClient:
    def __init__(self, ...):
        # ... init existant ...
        self._callbacks = CallbackRegistry()
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    # ─────────────────────────────────────────────────────────────────
    # Enregistrement des callbacks
    # ─────────────────────────────────────────────────────────────────

    def on_auth_error(self, secret_name: str):
        """
        Décorateur pour enregistrer un callback par secret.
        
        Usage:
            @client.on_auth_error("anthropic_api_key")
            async def handle(new_value: str) -> None:
                anthropic.api_key = new_value
        """
        def decorator(callback):
            self._callbacks.register_specific(secret_name, callback)
            return callback
        return decorator

    def on_any_auth_error(self, callback):
        """
        Décorateur pour enregistrer un callback global.
        
        Usage:
            @client.on_any_auth_error
            async def handle(secret_name: str, new_value: str) -> None:
                logger.info("rotated", secret=secret_name)
        """
        self._callbacks.register_global(callback)
        return callback

    # ─────────────────────────────────────────────────────────────────
    # Notification et refresh
    # ─────────────────────────────────────────────────────────────────

    async def notify_auth_error(self, secret_name: str) -> None:
        """
        Appelé par l'application quand elle détecte une erreur d'auth
        liée à ce secret. Déclenche un refresh + callbacks.
        
        Idempotent : si plusieurs coroutines appellent simultanément
        pour le même secret, un seul refresh est effectué.
        
        Raises:
            SecretRefreshFailed: si le refresh échoue
        """
        # Lock par secret pour éviter les refreshs concurrents
        if secret_name not in self._refresh_locks:
            self._refresh_locks[secret_name] = asyncio.Lock()

        async with self._refresh_locks[secret_name]:
            # Invalider le cache
            self._cache.invalidate(secret_name)

            # Tenter le refresh
            try:
                new_value = await self._fetch_and_cache(secret_name)
            except Exception as e:
                raise SecretRefreshFailed(
                    secret_name=secret_name,
                    reason=self._classify_error(e),
                    http_status=getattr(e, "status_code", None),
                    original_error=e,
                ) from e

            # Appeler les callbacks (spécifiques puis globaux)
            await self._callbacks.fire(secret_name, new_value)

    def _classify_error(self, error: Exception) -> str:
        """Classifie une erreur de refresh en reason string."""
        status = getattr(error, "status_code", None)
        if status == 401:
            return "api_key_revoked"
        elif status == 403:
            return "permission_denied"
        elif status == 404:
            return "secret_not_found"
        elif status and status >= 500:
            return "vault_error"
        else:
            return "vault_unreachable"

    def get_secret(
        self,
        secret_name: str,
        force_refresh: bool = False,
    ) -> str:
        """
        Retourne la valeur déchiffrée du secret.
        
        Args:
            secret_name: Nom du secret (peut contenir un path)
            force_refresh: Si True, bypass le cache
        """
        if force_refresh:
            self._cache.invalidate(secret_name)

        cached = self._cache.get(secret_name)
        if cached is not None:
            return cached

        # Fetch synchrone (wrapping de l'async)
        return asyncio.get_event_loop().run_until_complete(
            self._fetch_and_cache(secret_name)
        )

    async def get_secret_async(
        self,
        secret_name: str,
        force_refresh: bool = False,
    ) -> str:
        """Version async de get_secret."""
        if force_refresh:
            self._cache.invalidate(secret_name)

        cached = self._cache.get(secret_name)
        if cached is not None:
            return cached

        return await self._fetch_and_cache(secret_name)

    # ─────────────────────────────────────────────────────────────────
    # Context manager
    # ─────────────────────────────────────────────────────────────────

    def using_secret(
        self,
        secret_name: str,
        auth_errors: tuple[Type[Exception], ...] = (),
    ) -> "SecretContext":
        """
        Context manager pour utiliser un secret avec retry automatique.
        
        Usage:
            async with client.using_secret(
                "github_token",
                auth_errors=(github.AuthError,)
            ) as token:
                repos = await github.list_repos(token=token)
        """
        from .context import SecretContext
        return SecretContext(self, secret_name, auth_errors)
```

### `context.py` — Context manager

```python
# harpocrate_sdk/context.py

from typing import Type
from .exceptions import SecretRefreshFailed


class SecretContext:
    """
    Context manager avec retry automatique sur auth error.
    
    Réessaie UNE FOIS après refresh. Si échec encore → exception remontée.
    """

    def __init__(
        self,
        client,
        secret_name: str,
        auth_errors: tuple[Type[Exception], ...],
    ):
        self._client = client
        self._secret_name = secret_name
        self._auth_errors = auth_errors
        self._value: str = None
        self._retried = False

    async def __aenter__(self) -> str:
        self._value = await self._client.get_secret_async(self._secret_name)
        return self._value

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            return False  # Pas d'exception, tout va bien

        if not self._auth_errors:
            return False  # Pas de auth_errors configurées, on laisse remonter

        if not issubclass(exc_type, self._auth_errors):
            return False  # Exception non reconnue comme auth error

        if self._retried:
            return False  # Déjà retenté, on laisse remonter

        # Auth error détectée → refresh et retry
        self._retried = True

        try:
            await self._client.notify_auth_error(self._secret_name)
        except SecretRefreshFailed:
            return False  # Refresh échoué → laisser remonter l'exception originale

        # Récupérer la nouvelle valeur et réexécuter le bloc
        # Note : __aexit__ ne peut pas réexécuter le bloc directement.
        # On supprime l'exception et on expose la nouvelle valeur via une
        # propriété que l'application peut consulter.
        self._value = await self._client.get_secret_async(self._secret_name)

        # On supprime l'exception (return True) pour permettre à l'application
        # de récupérer la nouvelle valeur via context.value
        # MAIS : on ne peut pas réexécuter le bloc automatiquement.
        # L'approche correcte est de signaler via une exception dédiée.
        raise SecretRotatedRetry(self._secret_name, self._value) from exc_val

    @property
    def value(self) -> str:
        return self._value


class SecretRotatedRetry(Exception):
    """
    Levée par using_secret quand un retry est nécessaire.
    L'application doit la gérer pour utiliser la nouvelle valeur.
    
    Usage recommandé :
        try:
            async with client.using_secret("key", auth_errors=(AuthErr,)) as key:
                result = await call_api(key)
        except SecretRotatedRetry as e:
            result = await call_api(e.new_value)
    """
    def __init__(self, secret_name: str, new_value: str):
        self.secret_name = secret_name
        self.new_value = new_value
        super().__init__(f"Secret '{secret_name}' was rotated, retry with new value")
```

### `cache.py` — Invalidation

```python
# harpocrate_sdk/cache.py (modification)

class SecretCache:
    def __init__(self):
        self._store: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def invalidate(self, key: str) -> None:
        """Invalide une entrée du cache."""
        self._store.pop(key, None)

    def invalidate_all(self) -> None:
        """Invalide tout le cache (ex: rotation HMAC_KEY)."""
        self._store.clear()
```

---

## Exemples d'usage complets

### Exemple 1 — Callbacks par secret

```python
import asyncio
from harpocrate import VaultClient
import anthropic

# Initialisation
client = VaultClient.from_env()
anthropic_client = anthropic.Anthropic(
    api_key=client.get_secret("ag-flow-prod/anthropic_api_key")
)

# Enregistrer le callback de rotation
@client.on_auth_error("ag-flow-prod/anthropic_api_key")
async def on_anthropic_key_rotated(new_value: str) -> None:
    """Mis à jour automatiquement quand la clé est rotée."""
    anthropic_client.api_key = new_value
    logger.info("anthropic_api_key updated after rotation")

# Dans le code applicatif
async def generate(prompt: str) -> str:
    try:
        return anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": prompt}]
        ).content[0].text
    except anthropic.AuthenticationError:
        # Notifier le SDK → refresh + callback appelé automatiquement
        await client.notify_auth_error("ag-flow-prod/anthropic_api_key")
        # Après ça, anthropic_client.api_key a déjà été mis à jour par le callback
        return anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": prompt}]
        ).content[0].text
```

### Exemple 2 — Callback global

```python
# Filet de sécurité : logger toutes les rotations
@client.on_any_auth_error
async def log_all_rotations(secret_name: str, new_value: str) -> None:
    logger.warning(
        "secret_rotated",
        secret=secret_name,
        # JAMAIS loguer new_value — c'est le secret en clair
    )
```

### Exemple 3 — Context manager

```python
from harpocrate import VaultClient, SecretRotatedRetry
import httpx

client = VaultClient.from_env()

async def call_github_api(endpoint: str) -> dict:
    try:
        async with client.using_secret(
            "ag-flow-prod/github_token",
            auth_errors=(httpx.HTTPStatusError,)
        ) as token:
            async with httpx.AsyncClient() as http:
                response = http.get(
                    f"https://api.github.com/{endpoint}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                return response.json()
    except SecretRotatedRetry as e:
        # Le SDK a détecté la rotation et fourni la nouvelle valeur
        async with httpx.AsyncClient() as http:
            response = http.get(
                f"https://api.github.com/{endpoint}",
                headers={"Authorization": f"Bearer {e.new_value}"}
            )
            response.raise_for_status()
            return response.json()
```

### Exemple 4 — Révocation de l'API key du SDK

```python
async def safe_generate(prompt: str) -> str:
    try:
        return await generate(prompt)
    except SecretRefreshFailed as e:
        if e.reason == "api_key_revoked":
            logger.critical(
                "vault_api_key_revoked",
                message="Harpocrate API key has been revoked. "
                        "Contact admin to provision a new key.",
            )
            raise SystemExit(1)
        elif e.reason == "vault_unreachable":
            logger.error("vault_unreachable", error=str(e.original_error))
            raise
        else:
            raise
```

### Exemple 5 — Plusieurs callbacks pour le même secret

```python
@client.on_auth_error("prod/database_password")
async def update_asyncpg_pool(new_password: str) -> None:
    """Recrée le pool asyncpg avec le nouveau mot de passe."""
    await app.state.db_pool.close()
    app.state.db_pool = await asyncpg.create_pool(
        dsn=f"postgresql://harpocrate:{new_password}@postgres:5432/harpocrate"
    )

@client.on_auth_error("prod/database_password")
async def notify_ops(new_password: str) -> None:
    """Notifier l'équipe ops qu'une rotation a eu lieu."""
    await send_slack_alert("Database password rotated and pool restarted")
```

---

## Tests

### `tests/test_callbacks.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from harpocrate import VaultClient


@pytest.fixture
def client(mock_vault):
    return VaultClient(url="http://localhost", token="hrp_test_...")


async def test_on_auth_error_decorator_registers_callback(client):
    called_with = []

    @client.on_auth_error("my_secret")
    async def cb(new_value: str):
        called_with.append(new_value)

    await client._callbacks.fire("my_secret", "new_value_123")
    assert called_with == ["new_value_123"]


async def test_on_any_auth_error_called_after_specific(client):
    order = []

    @client.on_auth_error("my_secret")
    async def specific(new_value):
        order.append("specific")

    @client.on_any_auth_error
    async def global_cb(secret_name, new_value):
        order.append("global")

    await client._callbacks.fire("my_secret", "val")
    assert order == ["specific", "global"]


async def test_callback_exception_does_not_block_others(client):
    called = []

    @client.on_auth_error("my_secret")
    async def bad_cb(new_value):
        raise RuntimeError("oops")

    @client.on_auth_error("my_secret")
    async def good_cb(new_value):
        called.append(new_value)

    # Ne doit pas lever malgré bad_cb
    await client._callbacks.fire("my_secret", "val")
    assert called == ["val"]


async def test_sync_callback_works(client):
    called = []

    @client.on_auth_error("my_secret")
    def sync_cb(new_value: str):  # sync, pas async
        called.append(new_value)

    await client._callbacks.fire("my_secret", "val")
    assert called == ["val"]
```

### `tests/test_notify_auth_error.py`

```python
async def test_notify_auth_error_refreshes_cache(client, mock_vault):
    mock_vault.set_secret("my_secret", "old_value")
    client.get_secret("my_secret")  # peuple le cache

    mock_vault.set_secret("my_secret", "new_value")  # rotation côté vault
    await client.notify_auth_error("my_secret")

    assert client.get_secret("my_secret") == "new_value"


async def test_notify_auth_error_calls_callbacks(client, mock_vault):
    mock_vault.set_secret("my_secret", "new_value")
    received = []

    @client.on_auth_error("my_secret")
    async def cb(new_value):
        received.append(new_value)

    await client.notify_auth_error("my_secret")
    assert received == ["new_value"]


async def test_notify_auth_error_concurrent_calls_single_refresh(client, mock_vault):
    """Deux appels simultanés → un seul refresh effectué."""
    refresh_count = 0
    original_fetch = client._fetch_and_cache

    async def counted_fetch(name):
        nonlocal refresh_count
        refresh_count += 1
        return await original_fetch(name)

    client._fetch_and_cache = counted_fetch
    mock_vault.set_secret("my_secret", "new_value")

    # Deux appels simultanés
    await asyncio.gather(
        client.notify_auth_error("my_secret"),
        client.notify_auth_error("my_secret"),
    )

    assert refresh_count == 1


async def test_notify_auth_error_raises_on_404(client, mock_vault):
    mock_vault.delete_secret("my_secret")

    with pytest.raises(SecretRefreshFailed) as exc:
        await client.notify_auth_error("my_secret")

    assert exc.value.reason == "secret_not_found"
    assert exc.value.http_status == 404


async def test_notify_auth_error_raises_on_api_key_revoked(client, mock_vault):
    mock_vault.revoke_api_key()

    with pytest.raises(SecretRefreshFailed) as exc:
        await client.notify_auth_error("my_secret")

    assert exc.value.reason == "api_key_revoked"
    assert exc.value.http_status == 401


async def test_notify_auth_error_raises_on_vault_unreachable(client, mock_vault):
    mock_vault.go_offline()

    with pytest.raises(SecretRefreshFailed) as exc:
        await client.notify_auth_error("my_secret")

    assert exc.value.reason == "vault_unreachable"
    assert exc.value.http_status is None
```

### `tests/test_using_secret.py`

```python
class FakeAuthError(Exception):
    pass


async def test_using_secret_normal_usage(client, mock_vault):
    mock_vault.set_secret("my_key", "secret_value")

    async with client.using_secret("my_key") as key:
        assert key == "secret_value"


async def test_using_secret_triggers_retry_on_auth_error(client, mock_vault):
    mock_vault.set_secret("my_key", "old_value")
    mock_vault.set_secret("my_key", "new_value")  # sera retourné après refresh

    attempts = []

    try:
        async with client.using_secret("my_key", auth_errors=(FakeAuthError,)) as key:
            attempts.append(key)
            raise FakeAuthError("401")
    except SecretRotatedRetry as e:
        assert e.new_value == "new_value"
        attempts.append(e.new_value)

    assert len(attempts) == 2


async def test_using_secret_non_auth_error_propagates(client, mock_vault):
    mock_vault.set_secret("my_key", "value")

    with pytest.raises(ValueError):
        async with client.using_secret("my_key", auth_errors=(FakeAuthError,)) as key:
            raise ValueError("not an auth error")


async def test_using_secret_no_retry_if_refresh_fails(client, mock_vault):
    mock_vault.set_secret("my_key", "value")
    mock_vault.delete_secret("my_key")  # supprimé pendant l'utilisation

    with pytest.raises(FakeAuthError):
        async with client.using_secret("my_key", auth_errors=(FakeAuthError,)) as key:
            raise FakeAuthError("401")
    # SecretRefreshFailed → on laisse remonter l'exception originale
```

---

## Publication PyPI

```toml
# pyproject.toml

[project]
name = "harpocrate-sdk"
version = "0.3.0"
description = "Python SDK for Harpocrate E2E encrypted secrets vault"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "cryptography>=42",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "pytest-mock"]
```

```bash
# Build et publication
python -m build --sdist
twine upload dist/harpocrate_sdk-0.3.0.tar.gz
```

**Changelog 0.3.0** :
- Ajout `on_auth_error(secret_name)` décorateur par secret
- Ajout `on_any_auth_error` décorateur global
- Ajout `notify_auth_error(secret_name)` avec idempotence sous lock
- Ajout `SecretRefreshFailed` avec classification par reason
- Ajout `using_secret()` context manager avec `SecretRotatedRetry`
- Ajout `force_refresh=True` sur `get_secret()`
- Ajout `get_secret_async()` pour contextes async natifs
- Ajout `cache.invalidate(key)` et `cache.invalidate_all()`

---

## Critères de succès

1. ✅ `@client.on_auth_error("key")` enregistre le callback
2. ✅ `@client.on_any_auth_error` enregistre le callback global
3. ✅ Callbacks spécifiques appelés avant le global
4. ✅ Callback qui lève une exception ne bloque pas les suivants
5. ✅ Callbacks sync et async fonctionnent tous les deux
6. ✅ `notify_auth_error` invalide le cache et refetch
7. ✅ `notify_auth_error` concurrent → un seul refresh effectué (lock)
8. ✅ `notify_auth_error` appelle callbacks après refresh réussi
9. ✅ `notify_auth_error` lève `SecretRefreshFailed` si 401 (api_key_revoked)
10. ✅ `notify_auth_error` lève `SecretRefreshFailed` si 404 (secret_not_found)
11. ✅ `notify_auth_error` lève `SecretRefreshFailed` si vault down (vault_unreachable)
12. ✅ `get_secret(force_refresh=True)` bypass le cache
13. ✅ `using_secret()` fournit la valeur courante
14. ✅ `using_secret()` déclenche retry sur auth_errors spécifiées
15. ✅ `using_secret()` laisse remonter les exceptions non-auth
16. ✅ `using_secret()` ne boucle pas si refresh échoue
17. ✅ `SecretRotatedRetry` expose `new_value`
18. ✅ `SecretRefreshFailed` expose `reason`, `http_status`, `original_error`
19. ✅ Tests complets (callbacks, notify, context manager)
20. ✅ PyPI `harpocrate-sdk==0.3.0` publié (sdist)

## Pièges connus

- **`asyncio.get_event_loop().run_until_complete()`** dans `get_secret()` synchrone : si appelé depuis un contexte déjà async (event loop déjà active), ça crashe. Utiliser `get_secret_async()` dans les contextes async natifs. Documenter clairement la distinction.
- **Lock par secret dans `notify_auth_error`** : les locks sont créés à la demande dans `_refresh_locks`. Si un grand nombre de secrets différents génèrent des erreurs simultanément, le dict grossit. Pas un problème en pratique (nombre de secrets par application typiquement <100).
- **`SecretRotatedRetry` dans `using_secret`** : le context manager ne peut pas réexécuter le bloc automatiquement (limitation Python). L'application doit attraper `SecretRotatedRetry` et réexécuter elle-même. C'est un compromis entre simplicité et magie — documenté clairement.
- **Callbacks qui ne connaissent pas la `decryption_key`** : le callback reçoit la valeur déchiffrée. Il ne doit jamais la loguer, la sérialiser, ou la persister. Documenter dans les exemples.
- **Thread safety** : le SDK est conçu pour asyncio. Si l'application est multi-thread (threads Python natifs, pas asyncio), des race conditions sont possibles sur le cache. Hors scope — asyncio est le modèle cible.
- **Révocation de l'API key du SDK** : `SecretRefreshFailed(reason="api_key_revoked")` est le signal que le SDK lui-même ne peut plus rien faire. L'application doit le traiter comme une erreur fatale et s'arrêter (ou attendre une nouvelle configuration). Ne pas retry en boucle.

## Ce qui suit

- **Lot 23** — etcd 3 nœuds cross-host (pve1 + pve2), élimination du SPOF etcd
- **Lot 24** — Hypothèse C : réplication applicative Harpocrate → Harpocrate (multi-instance, E2E préservé)
- **Lot 25** — SDK npm `@harpocrate/sdk` avec les mêmes patterns (D2, callbacks, context manager)
