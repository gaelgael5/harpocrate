"""Schémas Pydantic des cultures — /v1/admin/cultures (migration 034)."""

from __future__ import annotations

import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

# Code ISO 639-1, même contrainte que le CHECK de la table : validé avant toute requête.
CULTURE_CODE_PATTERN = r"^[a-z]{2}$"


class CultureItem(BaseModel):
    code: str
    english_name: str
    native_name: str | None
    enabled: bool
    is_default: bool
    updated_at: datetime.datetime


class CultureListResponse(BaseModel):
    items: list[CultureItem]


class CultureUpdate(BaseModel):
    """Corps de PATCH /v1/admin/cultures/{code}.

    `is_default` n'accepte que `true` : on change de culture par défaut en en désignant
    une autre, jamais en retirant le drapeau (il doit toujours exister un repli).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    is_default: Literal[True] | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        if self.enabled is None and self.is_default is None:
            raise ValueError("at least one of enabled, is_default must be provided")
        return self
