"""Cache JWKS — récupère et met en cache les clés publiques Keycloak."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

# Mapping kid → JWK dict brut (au format JSON du JWKS endpoint)
_keys: dict[str, Any] = {}
_refresh_lock: asyncio.Lock = asyncio.Lock()


def _jwks_url() -> str:
    base = f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"
    return f"{base}/protocol/openid-connect/certs"


async def _fetch_jwks() -> None:
    """Récupère et remplace le cache JWKS depuis Keycloak."""
    url = _jwks_url()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    new_keys: dict[str, Any] = {
        key["kid"]: key for key in data.get("keys", []) if "kid" in key
    }
    _keys.clear()
    _keys.update(new_keys)
    logger.info("jwks_refreshed", count=len(new_keys))


async def prefetch_jwks() -> None:
    """Appel au démarrage — best-effort : log et continue si Keycloak injoignable."""
    try:
        await _fetch_jwks()
    except Exception as exc:
        logger.warning("jwks_prefetch_failed", error=str(exc))


async def get_jwks_key(kid: str) -> Any:
    """Retourne le JWK dict pour le kid donné.

    Si le kid est inconnu, tente un refresh. Lève ValueError si toujours inconnu.
    """
    if kid not in _keys:
        async with _refresh_lock:
            if kid not in _keys:
                logger.info("jwks_unknown_kid_refresh", kid=kid)
                await _fetch_jwks()
    if kid not in _keys:
        raise ValueError(f"Unknown kid: {kid}")
    return _keys[kid]


async def jwks_refresh_loop() -> None:
    """Background task — rafraîchit le cache JWKS toutes les heures."""
    while True:
        await asyncio.sleep(3600)
        try:
            await _fetch_jwks()
        except Exception as exc:
            logger.error("jwks_refresh_failed", error=str(exc))
