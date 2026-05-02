"""Expose un contrat OpenAPI filtre pour les seules routes acceptant une API key.

- GET /v1/openapi-api-key.json  -> schema OpenAPI reduit (endpoints hrpv_* OK)
- GET /v1/api-docs               -> Swagger UI standalone pointant vers le schema

Reference : OVERVIEW.md section 6 (table d'eligibilite JWT vs API key).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


# Endpoints qui acceptent un token API key (hrpv_*) ou public.
# Source de verite : table OVERVIEW.md section 6.
# Tuple (path_template, http_method_lowercase).
_API_KEY_ENDPOINTS: set[tuple[str, str]] = {
    # Public (sans auth)
    ("/v1/health", "get"),
    ("/v1/config/public", "get"),
    ("/v1/config/keycloak", "get"),
    ("/v1/config/auth-modes", "get"),
    # Wallets (lecture scopee a l'api key)
    ("/v1/wallets", "get"),
    ("/v1/wallets/{wallet_id}", "get"),
    ("/v1/wallets/{wallet_id}/export", "get"),
    ("/v1/wallets/{wallet_id}/my-api-key-grant", "get"),
    ("/v1/wallets/{wallet_id}/tree", "get"),
    # Secrets (toutes les operations selon les permissions du token)
    ("/v1/wallets/{wallet_id}/secrets", "get"),
    ("/v1/wallets/{wallet_id}/secrets", "post"),
    ("/v1/wallets/{wallet_id}/secrets/placeholder", "post"),
    ("/v1/wallets/{wallet_id}/secrets/{name}", "get"),
    ("/v1/wallets/{wallet_id}/secrets/{name}", "put"),
    ("/v1/wallets/{wallet_id}/secrets/{name}", "patch"),
    ("/v1/wallets/{wallet_id}/secrets/{name}", "delete"),
    ("/v1/wallets/{wallet_id}/secrets/{name}/populate", "post"),
    ("/v1/wallets/{wallet_id}/secrets/{name}/descriptor", "get"),
    # Audit log (filtre force aux propres actions de l'api key)
    ("/v1/audit-log", "get"),
    # Self-introspection api key (pour le SDK)
    ("/v1/api-keys/{api_key_id}/wallet-id", "get"),
}


@router.get("/openapi-api-key.json", include_in_schema=False)
async def api_key_openapi_schema(request: Request) -> dict[str, Any]:
    """Retourne le schema OpenAPI filtre aux endpoints utilisables par API key."""
    full: dict[str, Any] = request.app.openapi()
    filtered_paths: dict[str, Any] = {}
    for path, methods in full.get("paths", {}).items():
        kept = {
            method: spec
            for method, spec in methods.items()
            if (path, method.lower()) in _API_KEY_ENDPOINTS
        }
        if kept:
            filtered_paths[path] = kept

    return {
        **full,
        "paths": filtered_paths,
        "info": {
            **full.get("info", {}),
            "title": "Harpocrate — API Key endpoints",
            "description": (
                "Sous-ensemble des endpoints Harpocrate accessibles avec un token "
                "API key (prefixe `hrpv_*`). Authentification : header "
                "`Authorization: Bearer hrpv_<token>`. Les endpoints reserves aux "
                "humains (gestion de wallets, grants, api-keys, /me/*) ne sont pas "
                "exposes ici."
            ),
        },
    }


@router.get("/api-docs", include_in_schema=False)
async def api_docs() -> HTMLResponse:
    """Sert un Swagger UI standalone qui charge le schema filtre."""
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <title>Harpocrate — API Key Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>body { margin: 0; font-family: sans-serif; }</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: '/v1/openapi-api-key.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        defaultModelsExpandDepth: -1,
      });
    };
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
