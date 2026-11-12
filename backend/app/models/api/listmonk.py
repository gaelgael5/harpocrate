"""Schémas Pydantic du paramétrage Listmonk — /v1/admin/listmonk (migrations 035, 036)."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.models.db.listmonk_connection import ListmonkConnectionView
from app.services.listmonk_connection import validate_listmonk_url

# Miroir du CHECK de la migration 035 et de `services.listmonk_templates.PURPOSES`.
Purpose = Literal["recovery"]


class ListmonkTemplateItem(BaseModel):
    purpose: Purpose
    culture_code: str
    template_id: int
    updated_at: datetime.datetime


class ListmonkSettingsResponse(BaseModel):
    connection: ListmonkConnectionView | None
    purposes: list[Purpose]
    templates: list[ListmonkTemplateItem]


class ListmonkConnectionUpdate(BaseModel):
    """Corps de PUT /v1/admin/listmonk/connection et de POST …/connection/test.

    `token` absent = garder le token enregistré : l'IHM ne le connaît pas et ne peut donc
    pas le renvoyer.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    api_user: str = Field(min_length=1, max_length=256)
    token: SecretStr | None = Field(default=None, min_length=1, max_length=1024)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return validate_listmonk_url(value.strip())

    @field_validator("api_user")
    @classmethod
    def _strip_user(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("api_user must not be blank")
        return stripped


class ListmonkTemplateUpdate(BaseModel):
    """Corps de PUT /v1/admin/listmonk/templates/{purpose}/{culture_code}."""

    model_config = ConfigDict(extra="forbid")

    # Borne haute = INTEGER PostgreSQL : au-delà, la base lèverait une erreur 500.
    template_id: int = Field(gt=0, le=2_147_483_647)
