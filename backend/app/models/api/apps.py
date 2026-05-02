"""Schémas Pydantic pour l'endpoint /v1/apps — menu launcher cross-suite."""
from __future__ import annotations

from pydantic import BaseModel, HttpUrl


class AppEntry(BaseModel):
    """Entrée du menu launcher d'applications."""

    key: str
    label: str
    icon: HttpUrl
    url: HttpUrl


class AppsResponse(BaseModel):
    """Réponse de l'endpoint GET /v1/apps."""

    urls: list[AppEntry]
