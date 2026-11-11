"""Modèle DB pour la table listmonk_templates — template par type de mail et culture
(migration 035)."""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel


class ListmonkTemplateRow(BaseModel):
    """Représentation d'une ligne listmonk_templates issue de la DB."""

    purpose: str
    culture_code: str
    template_id: int
    updated_by_user_id: UUID | None
    updated_at: datetime.datetime


class ResolvedTemplate(BaseModel):
    """Template retenu pour un envoi, et la culture d'où il vient (celle de
    l'utilisateur ou la culture par défaut) — journalisée pour expliquer un repli."""

    template_id: int
    culture_code: str
