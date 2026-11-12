"""Modèles de la connexion Listmonk (migration 036)."""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, SecretStr


class ListmonkConnectionRow(BaseModel):
    """Ligne listmonk_connection telle que lue en base (token encore chiffré)."""

    url: str
    api_user: str
    token_encrypted: bytes
    updated_by_user_id: UUID | None
    updated_at: datetime.datetime


class ListmonkConnection(BaseModel):
    """Connexion prête à l'emploi. `SecretStr` : le token ne s'affiche ni dans un repr,
    ni dans un log, ni dans un `model_dump()` — il ne se déballe qu'au point d'usage
    (en-tête Authorization)."""

    url: str
    api_user: str
    token: SecretStr


class ListmonkConnectionView(BaseModel):
    """Connexion telle que montrée à l'admin. Le token n'y figure JAMAIS : seulement s'il
    est lisible (`False` si HARPOCRATE_HMAC_KEY a changé depuis son enregistrement)."""

    url: str
    api_user: str
    token_readable: bool
    updated_at: datetime.datetime
