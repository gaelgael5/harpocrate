"""Wrapper httpx synchrone avec retry — LOT_09 SDK.

Gère :
  - Header Authorization: Bearer <token>
  - Base URL avec validation HTTPS (sauf HARPOCRATE_ALLOW_INSECURE=1)
  - Retry simple sur les erreurs de connexion (3 tentatives, backoff linéaire)
  - Conversion des erreurs HTTP en exceptions SDK

Sécurité :
  - Refuse http:// sauf si HARPOCRATE_ALLOW_INSECURE=1 (dev local)
  - Ne logue jamais le token ou les headers Authorization
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from harpocrate.exceptions import (
    PermissionDenied,
    PlaceholderNotPopulated,
    SecretNotFound,
    VaultHttpError,
)

_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0  # secondes


def _check_base_url(base_url: str) -> None:
    """Valide que l'URL est HTTPS (sauf mode insecure)."""
    allow_insecure = os.environ.get("HARPOCRATE_ALLOW_INSECURE", "0") == "1"
    if not allow_insecure and base_url.startswith("http://"):
        raise ValueError(
            "HTTPS required. Set HARPOCRATE_ALLOW_INSECURE=1 to allow HTTP (dev only)."
        )


class VaultHttpClient:
    """Client HTTP synchrone pour l'API Harpocrate.

    Utilise httpx en mode synchrone pour la compatibilité avec les scripts
    et les contextes non-async (install.sh, cron, CI).
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise le client HTTP.

        Paramètres :
            base_url : URL de base du serveur (ex: "https://vault.yoops.org")
            token    : token hrpv_* (Bearer)
            timeout  : timeout HTTP en secondes
        """
        base_url = base_url.rstrip("/")
        _check_base_url(base_url)
        self._base_url = base_url
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        """Headers HTTP communs (Authorization non loggé)."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        """Construit l'URL complète."""
        return f"{self._base_url}{path}"

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """Convertit les codes HTTP en exceptions SDK."""
        if resp.status_code == 200 or resp.status_code == 201:
            return

        try:
            detail: Any = resp.json()
        except Exception:
            detail = resp.text

        if resp.status_code == 403:
            msg = ""
            if isinstance(detail, dict):
                msg = detail.get("detail", {}).get("message", "") if isinstance(detail.get("detail"), dict) else str(detail)
            raise PermissionDenied(msg or "Permission denied")

        if resp.status_code == 404:
            if isinstance(detail, dict) and isinstance(detail.get("detail"), dict):
                inner = detail["detail"]
                if inner.get("error") == "secret_not_found":
                    raise SecretNotFound(inner.get("message", "Secret not found"))
            raise SecretNotFound(f"Not found: {detail}")

        if resp.status_code == 424:
            # Placeholder sans valeur
            if isinstance(detail, dict) and isinstance(detail.get("detail"), dict):
                inner = detail["detail"]
                name = inner.get("details", {}).get("name", "unknown")
                descriptor = inner.get("details", {}).get("generation_descriptor")
                raise PlaceholderNotPopulated(name, descriptor)
            raise PlaceholderNotPopulated("unknown")

        raise VaultHttpError(resp.status_code, detail)

    def get(self, path: str, **params: Any) -> Any:
        """GET synchrone avec retry."""
        return self._request("GET", path, params=params or None)

    def post(self, path: str, json: Any = None) -> Any:
        """POST synchrone avec retry."""
        return self._request("POST", path, json=json)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Requête HTTP avec retry sur erreurs réseau."""
        url = self._url(path)
        last_exc: Exception = RuntimeError("No attempts made")

        for attempt in range(_MAX_RETRIES):
            try:
                resp = httpx.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json,
                    timeout=self._timeout,
                )
                self._raise_for_status(resp)
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
            except (VaultHttpError, PermissionDenied, SecretNotFound, PlaceholderNotPopulated):
                raise  # Pas de retry sur les erreurs applicatives

        raise VaultHttpError(0, f"Connection failed after {_MAX_RETRIES} attempts: {last_exc}")
