# Singleton

## Problème

Tu as besoin d'une seule instance d'un objet dans tout le process — une connexion DB, un bus d'events, un callback handler.

## Solution

En Python, le singleton le plus simple est une variable de module. Pas besoin de classe spéciale.

## Exemple

```python
# singleton.py — le module est le singleton

_instance = None

def get_instance():
    global _instance
    if _instance is None:
        _instance = ExpensiveResource()
    return _instance

# Ou encore plus simple avec @lru_cache
from functools import lru_cache

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

## Quand l'utiliser

- Une seule instance doit exister (connexion, pool, bus)
- L'objet est coûteux à créer et réutilisable
- Accès global nécessaire

## Quand ne PAS l'utiliser

- Tu peux passer l'objet en paramètre → injection de dépendance
- L'état mutable du singleton cause des bugs en concurrence → un pool ou un contexte par requête
- En tests → les singletons rendent les tests interdépendants. Préférer l'injection
