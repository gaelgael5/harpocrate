"""Modèle DB pour la table cultures — langues ISO 639-1 activables (migration 034)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel


class CultureRow(BaseModel):
    """Représentation d'une ligne cultures issue de la DB."""

    code: str
    english_name: str
    native_name: str | None
    enabled: bool
    is_default: bool
    updated_at: datetime.datetime
