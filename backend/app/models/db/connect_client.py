"""Modèle DB pour la table connect_clients — registre des applications (migration 033)."""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel


class ConnectClientRow(BaseModel):
    """Représentation d'une ligne connect_clients issue de la DB."""

    id: UUID
    client_id: str
    name: str
    description: str | None
    redirect_uris: list[str]
    active: bool
    created_by_user_id: UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
