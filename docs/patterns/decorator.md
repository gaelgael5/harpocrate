# Decorator

## Probleme
On veut ajouter des comportements transversaux (logging, retry, cache, auth) a des fonctions ou classes sans modifier leur code source. L'heritage cree des explosions combinatoires.

## Solution
Un decorateur enveloppe un objet/fonction et ajoute du comportement avant/apres l'appel original. Les decorateurs sont composables et independants.

## Exemple
```python
import functools
import logging

logger = logging.getLogger(__name__)

def with_retry(max_retries: int = 3, backoff: float = 2.0):
    """Decorateur retry avec backoff exponentiel pour les appels LLM."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = 1.0
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except RateLimitError:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"{func.__name__} rate limited, retry {attempt+1}")
                    await asyncio.sleep(delay)
                    delay *= backoff
        return wrapper
    return decorator

@with_retry(max_retries=20, backoff=2.0)
async def call_llm(provider: str, messages: list[dict]) -> str:
    return await llm_provider.invoke(provider, messages)
```

## Quand l'utiliser
- Comportements transversaux : retry, logging, metriques, cache, throttling
- Le comportement doit etre optionnel et composable (@retry + @log + @trace)
- On ne peut/veut pas modifier la fonction originale (librairie externe)
- Pattern tres idiomatique en Python avec `@decorator`

## Quand ne PAS l'utiliser
- Le comportement est specifique a une seule fonction (le mettre inline)
- Trop de decorateurs empiles rendent le debug difficile (>3-4)
- Le decorateur a besoin d'un etat mutable partage (preferer une classe)
