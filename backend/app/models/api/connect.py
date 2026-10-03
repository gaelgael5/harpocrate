"""Schémas Pydantic du flux « Se connecter avec Harpocrate » — registre des applications.

`extra="forbid"` sur les requêtes : un champ inattendu est refusé (422), jamais ignoré en
silence — une faute de frappe dans un champ de sécurité ne doit pas passer inaperçue.
"""

from __future__ import annotations

import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.connect_clients import normalize_redirect_uris

CLIENT_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


def _strip_name(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be blank")
    return stripped


class ConnectClientCreate(BaseModel):
    """Corps de POST /v1/admin/connect-clients."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    redirect_uris: list[str] = Field(min_length=1, max_length=10)

    _strip = field_validator("name")(_strip_name)

    @field_validator("redirect_uris")
    @classmethod
    def _check_redirect_uris(cls, value: list[str]) -> list[str]:
        return normalize_redirect_uris(value)


class ConnectClientUpdate(BaseModel):
    """Corps de PATCH /v1/admin/connect-clients/{id} — modification partielle.

    Le `client_id` n'est pas modifiable : c'est l'identifiant que les applications ont déjà
    configuré, le changer casserait leurs demandes en cours.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    redirect_uris: list[str] | None = Field(default=None, min_length=1, max_length=10)
    active: bool | None = None

    _strip = field_validator("name")(_strip_name)

    @field_validator("redirect_uris")
    @classmethod
    def _check_redirect_uris(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_redirect_uris(value)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field in ("name", "redirect_uris", "active"):
            # `description` peut être remise à null (effacement) ; les autres non.
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ConnectClientItem(BaseModel):
    """Une application du registre, telle que renvoyée à l'admin."""

    id: UUID
    client_id: str
    name: str
    description: str | None
    redirect_uris: list[str]
    active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ConnectClientListResponse(BaseModel):
    items: list[ConnectClientItem]
