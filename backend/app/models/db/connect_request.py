"""Modèle DB pour la table connect_requests — demandes de connexion en cours (migration 033)."""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ConnectRequestRow(BaseModel):
    """Une demande déposée par PAR, jointe à l'application qui l'a déposée.

    `sealed_jwe` et `code_hash` ne sont pas chargés ici : ils ne servent qu'à l'émission
    et à l'échange du code, qui les lisent par des requêtes dédiées.
    """

    id: UUID
    client_pk: UUID
    client_id: str
    client_name: str
    client_description: str | None
    client_active: bool
    redirect_uri: str
    state: str
    code_challenge: str
    requested_permissions: int
    requested_ttl_days: int | None
    app_public_jwk: dict[str, Any]
    status: str
    user_id: UUID | None
    wallet_id: UUID | None
    api_key_id: UUID | None
    expires_at: datetime.datetime
    created_at: datetime.datetime
