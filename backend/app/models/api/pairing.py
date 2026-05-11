"""DTOs Pydantic — appairage master/standby entre 2 instances Harpocrate (LOT 2)."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PairingRole = Literal["master", "standby"]
PairingStatus = Literal[
    "pending",
    "confirmed",
    "wizard",
    "completed",
    "expired",
    "failed",
]


class PairingInitRequest(BaseModel):
    """A appelle /init avec l'URL publique du standby pour générer un code."""

    partner_url: str = Field(..., min_length=1)


class PairingInitResponse(BaseModel):
    session_id: UUID
    code: str
    expires_in_seconds: int


class PairingAcceptRequest(BaseModel):
    """B appelle /accept avec l'URL master + le code 4 chiffres reçus de A."""

    master_url: str = Field(..., min_length=1)
    code: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("code_must_be_4_digits")
        return v


class PairingConfirmRequest(BaseModel):
    """B → A : confirm avec le code 4 chiffres et l'URL de B pour le pairing."""

    code: str
    standby_url: str = Field(..., min_length=1)

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("code_must_be_4_digits")
        return v


class PairingConfirmResponse(BaseModel):
    """A → B : payload retourné après création du node standby côté A."""

    master_host: str
    master_port: int
    replication_user: str
    replication_password: str
    application_name: str
    node_id: UUID


class PairingAcceptResponse(BaseModel):
    """B → caller : session locale créée après contact réussi avec A."""

    session_id: UUID


class PairingStatusResponse(BaseModel):
    """GET /pairing/{id}/status — état d'une session d'appairage."""

    session_id: UUID
    role: PairingRole
    status: PairingStatus
    partner_url: str | None
    current_step_idx: int
    expires_at: str
