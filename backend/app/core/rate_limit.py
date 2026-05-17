"""Rate limiting applicatif — S-5 du rapport d'audit.

Avant cette livraison, le threat-model T-13 affirmait « rate limiting sur
les endpoints d'auth » mais aucun mécanisme applicatif n'existait dans
`backend/app/` (grep `slowapi` / `RateLimit` = 0). Les seules protections
côté Argon2id sont coûteuses mais ne suffisent pas seules contre un
brute-force massif depuis une même IP.

Implémentation : dépendance FastAPI (`Depends(rate_limit_dep("5/minute"))`)
qui appelle la lib [`limits`](https://limits.readthedocs.io) directement,
en mode in-memory. On n'utilise pas le décorateur slowapi car il wrap le
handler avec `*args, **kwargs` ce qui empêche FastAPI de résoudre les
annotations forward-ref (`from __future__ import annotations`) en cherchant
les types dans les `__globals__` du wrapper slowapi au lieu de ceux du
module original.

Clé de bucket : IP appelante avec préférence pour le premier IP de
`X-Forwarded-For` quand un reverse-proxy de confiance le settre (Cloudflare
Tunnel, Caddy, Nginx). Voir `_key_by_ip`.

Pour un cluster multi-instances, les compteurs ne sont pas partagés —
choix de design Harpocrate (pas de Redis). La limite effective est donc
multipliée par le nombre de workers/instances, mais reste efficace contre
un brute-force aveugle depuis une même source IP.

Désactivable globalement via `HARPOCRATE_RATE_LIMIT_ENABLED=false`
(utile pour les tests qui font des batchs de requêtes).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status
from limits import RateLimitItem, parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from app.core.config import settings

# Storage et stratégie partagés pour tout le process (in-memory, per-worker).
_storage = MemoryStorage()
_strategy = MovingWindowRateLimiter(_storage)


def _key_by_ip(request: Request) -> str:
    """Clé de bucket = IP appelante.

    Priorité au premier IP de `X-Forwarded-For` quand le reverse-proxy
    le settre. Fallback sur `request.client.host`. Retourne `"unknown"`
    si même le client n'est pas accessible (cas pathologique des tests).
    """
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first
    if request.client is not None:
        return request.client.host
    return "unknown"


def _parse_limits(limit_spec: str) -> list[RateLimitItem]:
    """Parse `"5/minute;100/hour"` en liste de `RateLimitItem`."""
    parts = [p.strip() for p in limit_spec.split(";") if p.strip()]
    return [parse(p) for p in parts]


def rate_limit_dep(limit_spec: str) -> Callable[[Request], None]:
    """Construit une dépendance FastAPI qui vérifie la limite par IP.

    Utilisation :
        @router.post("/auth/login", dependencies=[Depends(rate_limit_dep("5/minute"))])
        async def login(...): ...

    Format `limit_spec` : `"5/minute"`, `"10/hour;100/day"` (`;` pour cumuler
    plusieurs fenêtres — toutes doivent être OK). Cf. doc `limits`.

    Lève `HTTPException(429)` quand une limite est dépassée. La réponse
    JSON suit le format Harpocrate `{"error": "rate_limit_exceeded", ...}`.
    """
    items = _parse_limits(limit_spec)

    def _check(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        key = _key_by_ip(request)
        # Namespace par chemin pour avoir des buckets distincts par route.
        # Sans ça, un appel à `/login` et un appel à `/recovery/start`
        # partageraient le même compteur — confus et trop restrictif.
        namespace = request.url.path
        for item in items:
            if not _strategy.hit(item, key, namespace):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "rate_limit_exceeded",
                        "message": f"Rate limit exceeded: {item}",
                    },
                    headers={"Retry-After": "60"},
                )

    return _check


def reset_in_memory_storage() -> None:
    """Vide le storage in-memory — utilitaire pour les tests."""
    _storage.reset()
