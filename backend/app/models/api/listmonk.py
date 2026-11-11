"""Schémas Pydantic du paramétrage Listmonk — /v1/admin/listmonk (migration 035)."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Miroir du CHECK de la migration 035 et de `services.listmonk_templates.PURPOSES`.
Purpose = Literal["recovery"]


class ListmonkTemplateItem(BaseModel):
    purpose: Purpose
    culture_code: str
    template_id: int
    updated_at: datetime.datetime


class ListmonkSettingsResponse(BaseModel):
    """État du paramétrage Listmonk.

    `configured` et `url` décrivent la connexion posée dans le .env de l'hôte, en
    lecture seule. Ni l'utilisateur ni le token n'y figurent : ce sont des secrets
    d'amorçage qui ne quittent pas le serveur.
    """

    configured: bool
    url: str
    purposes: list[Purpose]
    templates: list[ListmonkTemplateItem]


class ListmonkTemplateUpdate(BaseModel):
    """Corps de PUT /v1/admin/listmonk/templates/{purpose}/{culture_code}."""

    model_config = ConfigDict(extra="forbid")

    # Borne haute = INTEGER PostgreSQL : au-delà, la base lèverait une erreur 500.
    template_id: int = Field(gt=0, le=2_147_483_647)
