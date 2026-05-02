"""Endpoint GET /v1/apps — menu launcher cross-suite.

Lit apps.json à chaque requête (pas de cache mémoire) pour que les ops
puissent mettre à jour le fichier sans redémarrer le backend.

Si le fichier est absent ou contient du JSON invalide : retourne {"urls": []}.
Si une entrée individuelle est invalide (URL malformée…) : retourne {"urls": []}.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import ValidationError

from app.core.config import settings
from app.core.logging import logger
from app.core.security import JwtUser
from app.models.api.apps import AppEntry, AppsResponse

router = APIRouter(tags=["apps"])

_EMPTY = AppsResponse(urls=[])


@router.get("/apps", response_model=AppsResponse)
async def list_apps(_current_user: JwtUser) -> AppsResponse:
    """Retourne la liste des applications de la suite agflow/yoops.

    Auth : tout utilisateur JWT valide (require_jwt_user).
    Fallback silencieux : fichier manquant ou JSON invalide → {"urls": []}.
    """
    path = Path(settings.apps_file)

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("apps_file_not_found", path=str(path))
        return _EMPTY
    except OSError as exc:
        logger.warning("apps_file_read_error", path=str(path), error=str(exc))
        return _EMPTY

    try:
        data: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("apps_file_json_invalid", path=str(path), error=str(exc))
        return _EMPTY

    if not isinstance(data, dict):
        logger.warning("apps_file_not_object", path=str(path))
        return _EMPTY

    raw_urls = data.get("urls")
    if not isinstance(raw_urls, list):
        logger.warning("apps_file_urls_not_list", path=str(path))
        return _EMPTY

    entries: list[AppEntry] = []
    for item in raw_urls:
        try:
            entries.append(AppEntry.model_validate(item))
        except ValidationError as exc:
            logger.warning(
                "apps_file_entry_invalid",
                path=str(path),
                item=item,
                error=str(exc),
            )
            # Sémantique "all-or-nothing" : une entrée invalide vide tout le menu
            return _EMPTY

    return AppsResponse(urls=entries)
