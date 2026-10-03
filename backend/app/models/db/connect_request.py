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


class ConnectRequestWithCode(ConnectRequestRow):
    """Demande retrouvée par son code : de quoi vérifier l'échange et remettre le scellé."""

    sealed_jwe: str | None
    code_expires_at: datetime.datetime | None


class UndeliveredKey(BaseModel):
    """Clé créée pour une demande expirée sans que l'application l'ait jamais reçue (D13)."""

    request_id: UUID
    api_key_id: UUID
    wallet_id: UUID
    client_id: str
